black_box_query = """
with cte_test_uri as (
  select
    issue_id,
    field_value as test_uri
  from
    devtools.jira_issue_custom_values
  where
    field_name = 'Link to ERD or PRD'
),
cte_epic_story_link as (
  select
    source_issue_id,
    destination_issue_id
  from
    devtools.jira_issue_links
  where
    link_name = 'Epic-Story Link'
  group by
    1,
    2
),
cte_epic as (
  select
    destination_issue_id,
    field_value as epic_name
  from
    cte_epic_story_link t1
    join devtools.jira_issue_custom_values t2 on t1.source_issue_id = t2.issue_id
  where
    field_name = 'Epic Name'
  group by
    1,
    2
),
test_uri_all as (
  select
    test_uri
  from
    (
      select
        *,
        array_join(labels, ',') as labels_str
      from
        devtools.jira_issues
    ) tbl1
    left join cte_epic tbl2 on tbl1.issue_id = tbl2.destination_issue_id
    join devtools.jira_projects t2 on tbl1.project_id = t2.project_id
    join cte_test_uri tu on tbl1.issue_id = tu.issue_id
  where
    epic_name in (
      '{epic_name}'
    ) and labels_str not like '%offboarded%'
    and labels_str not like '%Blocked%'
   and status='Closed'
   and test_uri is not null
),
cte_executions as (
 select datestr, tc, city,
  count(CASE WHEN result = 'PASS' THEN result END ) AS passed_count,
  count(result) AS total_count
 from
  (
   select datestr, msg.traitsmap.test as tc, msg.starttime as execution_time, msg.traitsmap.city as city,
       CASE WHEN msg.traitsmap.result = 'true' THEN 'PASS' ELSE 'FAIL' END AS result
   from rawdata_user.kafka_hp_blackbox_result_subscriber_test_result_nodedup
   where DATE(datestr) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
      AND DATE(datestr) <= CURRENT_DATE
      AND REGEXP_REPLACE(msg.traitsmap.test, '/[^/]+$', '') in (SELECT * from test_uri_all)
  ) t
 group by 1, 2, 3
)
SELECT tc, pass_rate, passed_count, total_count,
   CASE WHEN pass_rate > 95 THEN '>95%'
      WHEN pass_rate BETWEEN 90 and 95 THEN '90-95%'
      WHEN pass_rate BETWEEN 80 and 90 THEN '80-90%'
      ELSE '<80%'
   END as reliability_bucket
FROM (
  SELECT tc, ROUND((CAST(sum(passed_count) AS DOUBLE)/ CAST(sum(total_count) AS DOUBLE)), 2)*100 as pass_rate, sum(passed_count) as passed_count,
      sum(total_count) as total_count
  from cte_executions
  group by tc
)
order by pass_rate
"""
bits_query = """
WITH cte_test_uri AS (
  SELECT issue_id, field_value AS test_uri
  FROM devtools.jira_issue_custom_values
  WHERE field_name = 'Link to ERD or PRD'
),
cte_epic_story_link AS (
  SELECT source_issue_id, destination_issue_id
  FROM devtools.jira_issue_links
  WHERE link_name = 'Epic-Story Link'
  GROUP BY 1, 2
),
cte_epic AS (
  SELECT destination_issue_id, field_value AS epic_name
  FROM cte_epic_story_link t1
  JOIN devtools.jira_issue_custom_values t2 ON t1.source_issue_id = t2.issue_id
  WHERE field_name = 'Epic Name'
  GROUP BY 1, 2
),
test_uri_all AS (
  SELECT test_uri
  FROM (
    SELECT *, array_join(labels, ',') AS labels_str
    FROM devtools.jira_issues
  ) tbl1
  LEFT JOIN cte_epic tbl2 ON tbl1.issue_id = tbl2.destination_issue_id
  JOIN devtools.jira_projects t2 ON tbl1.project_id = t2.project_id
  JOIN cte_test_uri tu ON tbl1.issue_id = tu.issue_id
  WHERE epic_name IN ('{epic_name}')
    AND labels_str NOT LIKE '%offboarded%'
    AND labels_str NOT LIKE '%Blocked%'
    AND status = 'Closed'
),
raw_tc_data AS (
  SELECT msg.uuid, msg.uri, msg.updated_on
  FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testcase_nodedup
  WHERE msg.uri IN (SELECT test_uri FROM test_uri_all)
    AND DATE(datestr) > CURRENT_DATE - INTERVAL '600' DAY
),
max_updated_on_table AS (
  SELECT msg.uri AS uri, MAX(msg.updated_on) AS max_updated_on
  FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testcase_nodedup
  WHERE DATE(datestr) > CURRENT_DATE - INTERVAL '600' DAY
  GROUP BY msg.uri
),
latest_tc_data AS (
  SELECT raw_tc_data.uuid, raw_tc_data.uri
  FROM raw_tc_data
  INNER JOIN max_updated_on_table
  ON raw_tc_data.uri = max_updated_on_table.uri
     AND raw_tc_data.updated_on = max_updated_on_table.max_updated_on
),
final_cte AS (
  SELECT testcase.uri AS test_uri,
    ROUND((CAST(SUM(CASE WHEN testrun.msg.status = 'passed' THEN 1 ELSE 0 END) AS DOUBLE)/ CAST(COUNT(testrun.datestr) AS DOUBLE)), 2)*100 AS pass_rate,
    SUM(CASE WHEN testrun.msg.status = 'passed' THEN 1 ELSE 0 END) AS passed_count,
    COUNT(testrun.datestr) AS total_count
  FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testrun_nodedup testrun
  JOIN latest_tc_data testcase ON testcase.uuid = testrun.msg.testcase_uuid
  LEFT JOIN rawdata_user.kafka_hp_test_catalog_pipelinerun_nodedup pd ON testrun.msg.pipelinerun_uuid = pd.msg.pipelinerun.uuid
  WHERE testrun.msg.runner = 'placebo'
    AND DATE(testrun.datestr) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND DATE(pd.datestr) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    AND testrun.msg.status IN ('execution_failed', 'soft_fail', 'passed')
    AND element_at(pd.msg.pipelinerun.changeScope.services, 1) != 'bits-test-only-pipeline'
  GROUP BY testcase.uri
)
SELECT test_uri, pass_rate, passed_count, total_count,
  CASE 
    WHEN pass_rate > 95 THEN '>95%'
    WHEN pass_rate BETWEEN 90 AND 95 THEN '90-95%'
    WHEN pass_rate BETWEEN 80 AND 90 THEN '80-90%'
    ELSE '<80%'
  END AS reliability_bucket
FROM final_cte
ORDER BY pass_rate
"""

bits_optimized_query = """
SELECT 
    msg.status,
    msg.testcase_uuid,
    msg.test_run_error_results,
    msg.test_scopes,
    msg.test_stability_type,
    msg.reliability_pct,
    msg.stdout_turi,
    msg.service_routing_health_level,
    msg.tenancy
FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testrun_nodedup
WHERE datestr >= '{start_date} 00:00:00' 
    AND CAST(datestr AS DATE) < DATE_ADD('day', 1, DATE('{end_date}'))
    AND msg.testcase_uuid in ({uuid})
    AND msg.status IN ('execution_failed', 'soft_fail', 'passed')
    AND msg.runner = 'placebo'
"""

unsound_optimized_query = """
SELECT 
  msg.testcase_uuid,
  msg.status,
  msg.test_stability_type,
  msg.reliability_pct
FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testrun_nodedup
WHERE DATE(datestr) >= CURRENT_DATE - INTERVAL '{lookback_days}' DAY
  AND msg.testcase_uuid IN ({uuid})
  and msg.runner = 'placebo'
  and msg.test_stability_type = 'TEST_STABILITY_TYPE_UNSOUND'
  and msg.status IN ('execution_failed', 'soft_fail', 'passed')
"""

unsound_query = """
WITH tc AS (
  SELECT *
  FROM (
    SELECT DISTINCT msg.uuid, msg.asset_uuid, msg.uri,
      RANK() OVER (PARTITION BY msg.uri ORDER BY datestr DESC) AS rnk
    FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testcase_nodedup
    WHERE DATE(datestr) > CURRENT_DATE - INTERVAL '360' DAY
      AND msg.uri LIKE 'test%'
  ) t
  WHERE rnk = 1
),
cte_test_uri AS (
  SELECT issue_id, field_value AS test_uri
  FROM devtools.jira_issue_custom_values
  WHERE field_name = 'Link to ERD or PRD'
),
cte_epic_story_link AS (
  SELECT source_issue_id, destination_issue_id
  FROM devtools.jira_issue_links
  WHERE link_name = 'Epic-Story Link'
  GROUP BY 1, 2
),
cte_epic AS (
  SELECT destination_issue_id, field_value AS epic_name
  FROM cte_epic_story_link t1
  JOIN devtools.jira_issue_custom_values t2 ON t1.source_issue_id = t2.issue_id
  WHERE field_name = 'Epic Name'
  GROUP BY 1, 2
),
cte_gss_tc_list AS (
  SELECT created, issue_key, status, epic_name, project_name, test_uri, labels_str
  FROM (
    SELECT *, array_join(labels, ',') AS labels_str
    FROM devtools.jira_issues
  ) tbl1
  LEFT JOIN cte_epic tbl2 ON tbl1.issue_id = tbl2.destination_issue_id
  JOIN devtools.jira_projects t2 ON tbl1.project_id = t2.project_id
  JOIN cte_test_uri tu ON tbl1.issue_id = tu.issue_id
  WHERE epic_name IN ('BITS_E2E_Tests_{lob}')
),
cte_base AS (
  SELECT msg.testcase_uuid, uri, MAX(ts) AS max_upd
  FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testrun_nodedup t1
  JOIN tc t2 ON t1.msg.testcase_uuid = t2.uuid
  WHERE DATE(datestr) >= DATE('2023-01-01')
    AND msg.runner = 'placebo'
  GROUP BY 1, 2
)

SELECT x.uri, asset_uuid, msg.test_stability_type, msg.reliability_pct
FROM cte_base x
JOIN cte_gss_tc_list xx ON x.uri = xx.test_uri
JOIN rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testrun_nodedup y
  ON x.testcase_uuid = y.msg.testcase_uuid AND x.max_upd = y.ts
JOIN tc z ON x.testcase_uuid = z.uuid
WHERE DATE(datestr) > CURRENT_DATE - INTERVAL '{lookback_days}' DAY
  AND msg.test_stability_type = 'TEST_STABILITY_TYPE_UNSOUND'
GROUP BY 1, 2, 3, 4
ORDER BY 4;
"""

failing_query="""
SELECT
  datestr,
  test_uri,
  city_id,
  city_name,
  action_failure,
  error_message,
  error_assertions,
  run_status,
  stdout_turi,
  stderr_turi
FROM kirby_external_data.bits_failure_report_all_lob
WHERE lob = '{lob}'
  and DATE(datestr) > CURRENT_DATE - INTERVAL '{lookback_days}' DAY;
"""

failing_optimized_query = """
SELECT msg.status,msg.testcase_uuid,msg.test_scopes,msg.test_stability_type,msg.reliability_pct,msg.stdout_turi,msg.service_routing_health_level,msg.tenancy
FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testrun_nodedup
WHERE DATE(datestr) >= CURRENT_DATE - INTERVAL '{lookback_days}' DAY
  AND msg.testcase_uuid IN ({uuid})
  and msg.runner = 'placebo'
  and msg.status IN ('execution_failed', 'soft_fail')
"""



query_to_fetch_uri_1 = """
WITH cte_test_uri AS (
  SELECT issue_id, field_value AS test_uri
  FROM devtools.jira_issue_custom_values
  WHERE field_name = 'Link to ERD or PRD'
),
cte_epic_story_link AS (
  SELECT source_issue_id, destination_issue_id
  FROM devtools.jira_issue_links
  WHERE link_name = 'Epic-Story Link'
  GROUP BY 1, 2
),
cte_epic AS (
  SELECT destination_issue_id, field_value AS epic_name
  FROM cte_epic_story_link t1
  JOIN devtools.jira_issue_custom_values t2 ON t1.source_issue_id = t2.issue_id
  WHERE field_name = 'Epic Name'
  GROUP BY 1, 2
),
test_uri_all AS (
  SELECT test_uri
  FROM (
    SELECT *, array_join(labels, ',') AS labels_str
    FROM devtools.jira_issues
  ) tbl1
  LEFT JOIN cte_epic tbl2 ON tbl1.issue_id = tbl2.destination_issue_id
  JOIN devtools.jira_projects t2 ON tbl1.project_id = t2.project_id
  JOIN cte_test_uri tu ON tbl1.issue_id = tu.issue_id
  WHERE epic_name IN ('{epic_name}')
    AND labels_str NOT LIKE '%offboarded%'
    AND labels_str NOT LIKE '%Blocked%'
    AND status = 'Closed'
),
raw_tc_data AS (
  SELECT msg.uuid, msg.uri, msg.updated_on
  FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testcase_nodedup
  WHERE msg.uri IN (SELECT test_uri FROM test_uri_all)
    AND DATE(datestr) > CURRENT_DATE - INTERVAL '600' DAY
),
max_updated_on_table AS (
  SELECT msg.uri AS uri, MAX(msg.updated_on) AS max_updated_on
  FROM rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testcase_nodedup
  WHERE DATE(datestr) > CURRENT_DATE - INTERVAL '600' DAY
  GROUP BY msg.uri
)
SELECT raw_tc_data.uuid, raw_tc_data.uri
FROM raw_tc_data
INNER JOIN max_updated_on_table
ON raw_tc_data.uri = max_updated_on_table.uri
     AND raw_tc_data.updated_on = max_updated_on_table.max_updated_on
"""
black_box_optimized_query = """
SELECT 
    msg.traitsmap.test as blackbox_uri,
    REGEXP_REPLACE(msg.traitsmap.test, '/[^/]+$', '') as test_uri,
    datestr,
    msg.traitsmap.result as result,
    msg.traitsmap.city as city
FROM rawdata_user.kafka_hp_blackbox_result_subscriber_test_result_nodedup
WHERE datestr >= '{start_date}'
    AND CAST(datestr AS DATE) < DATE_ADD('day', 1, DATE('{end_date}'))
    AND REGEXP_REPLACE(msg.traitsmap.test, '/[^/]+$', '') IN ({test_uris})
"""

query_to_fetch_uri = """
WITH tc as (
  select * from (select
    distinct msg.uuid,
    msg.asset_uuid,
    msg.uri,
    RANK() OVER (
        PARTITION BY msg.uri
        ORDER BY
          datestr desc
      ) as rnk
  from
    rawdata_user.kafka_hp_dbevents_docstore_docstore_shared04_catalog_testcase_nodedup
  where
    DATE(datestr) > CURRENT_DATE - INTERVAL '360' DAY) t 
    where rnk=1
),
cte_test_uri as (
  select
    issue_id,
    field_value as test_uri
  from
    devtools.jira_issue_custom_values
  where
    field_name = 'Link to ERD or PRD'
),
cte_epic_story_link as (
  select
    source_issue_id,
    destination_issue_id
  from
    devtools.jira_issue_links
  where
    link_name = 'Epic-Story Link'
  group by
    1,
    2
),
cte_epic as (
  select
    destination_issue_id,
    field_value as epic_name
  from
    cte_epic_story_link t1
    join devtools.jira_issue_custom_values t2 on t1.source_issue_id = t2.issue_id
  where
    field_name = 'Epic Name'
  group by
    1,
    2
)
select
  tc.uuid as uuid,
  test_uri as uri
from
  (
    select
      *,
      array_join(labels, ',') as labels_str
    from
      devtools.jira_issues
  ) tbl1
  left join cte_epic tbl2 on tbl1.issue_id = tbl2.destination_issue_id
  join devtools.jira_projects t2 on tbl1.project_id = t2.project_id
  join cte_test_uri tu on tbl1.issue_id = tu.issue_id
  left join tc on LOWER(tu.test_uri) = LOWER(tc.uri)
where
  epic_name in (
    '{epic_name}'
  )
  AND tc.uuid IS NOT NULL
  AND test_uri IS NOT NULL
  """