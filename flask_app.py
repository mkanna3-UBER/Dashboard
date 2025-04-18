import importlib,subprocess,time,os,csv
from queryrunner_client import Client
from datetime import datetime
from flask import Flask, render_template,request,send_from_directory,session,send_file,redirect,url_for,flash
import requests, os
import csv
from flask_wtf.csrf import CSRFProtect
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from flask_wtf.csrf import CSRFProtect
import logging
from collections import defaultdict
from collections import Counter
from wtforms import IntegerField
from wtforms.validators import DataRequired, NumberRange
import sqlite3
from collections import defaultdict


# File-based SQLite DB
db_path = os.path.join(os.path.dirname(__file__), 'testcase_cache.db')
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

#for query
from querylist import *
from helper import update


app = Flask(__name__)
app.secret_key = "QueryRunner"
csrf = CSRFProtect(app)

EPIC_NAME_MAP = {
    'money': 'BITS_E2E_Tests_Money',
    'default':'default',
    'pricingincentives':'BITS_E2E_Tests_PricingIncentives'
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

class dummyForm_to_skip_csrf(FlaskForm):
    start_date = StringField('Start Date', validators=[DataRequired()])
    end_date = StringField('End Date', validators=[DataRequired()])
    submit = SubmitField('Submit')
class dummyForm_to_skip_csrf_1(FlaskForm):
    lookback_days = IntegerField('Lookback Days', validators=[DataRequired(), NumberRange(min=1, max=100)])
    submit = SubmitField('Submit')

@app.route('/')
@app.route('/money')
def dashboard():
    form = dummyForm_to_skip_csrf()
    return render_template('dashboard_money.html',lob='money', form=form)

@app.route('/pricingincentives')
def dashboard_1():
    form = dummyForm_to_skip_csrf()
    return render_template('dashboard_money.html',lob='pricingincentives', form=form)

@app.route('/blackbox', methods=['GET', 'POST'])
def blackbox():
    form = dummyForm_to_skip_csrf()
    lob = request.args.get('lob') or request.form.get('lob')
    
    if request.method == 'POST' and form.validate_on_submit():
        try:
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            epic_name = EPIC_NAME_MAP.get(lob.lower(), '')
            
            # Get test URIs from SQLite DB
            query = f"SELECT uri, uuid FROM {epic_name}"
            cursor.execute(query)
            test_rows = cursor.fetchall()
            test_uris = [f"'{row[0]}'" for row in test_rows]
            
            if not test_uris:
                logger.warning("No URIs found for selected LOB.")
                return render_template('blackbox_data.html', lob=lob, data=[], form=form)

            uri_in_clause = ",".join(test_uris)
            
            # Execute Presto query
            query = black_box_optimized_query.format(
                start_date=start_date,
                end_date=end_date,
                test_uris=uri_in_clause
            )
            
            qr_client = Client(user_email='mkanna3@ext.uber.com')
            result = qr_client.execute('presto', query)
            raw_data = [row for row in result.fetchall()]
            
            # Process data with city-wise analysis
            result_map = defaultdict(lambda: {
                "passed": 0,
                "total": 0,
                "city_stats": defaultdict(lambda: {"failed": 0, "total": 0})
            })
            
            # Aggregate results
            for row in raw_data:
                test_uri = row['test_uri']
                result = row['result']
                city = row['city'] or 'unknown'
                
                result_map[test_uri]["total"] += 1
                result_map[test_uri]["city_stats"][city]["total"] += 1
                result_map[test_uri]["blackbox_uri"]= row['blackbox_uri']
                
                if result == 'true':
                    result_map[test_uri]["passed"] += 1
                else:
                    result_map[test_uri]["city_stats"][city]["failed"] += 1
            
            # Calculate final statistics
            processed_data = []
            for uri, counts in result_map.items():
                pass_rate = round((counts["passed"] / counts["total"]) * 100, 2) if counts["total"] > 0 else 0
                
                # Calculate city failure rates and sort by failure count
                city_failures = []
                for city, stats in counts["city_stats"].items():
                    if stats["failed"] > 0:  # Only include cities with failures
                        failure_rate = round((stats["failed"] / stats["total"]) * 100, 2)
                        city_failures.append({
                            "city": city,
                            "failed_count": stats["failed"],
                            "total_count": stats["total"],
                            "failure_rate": failure_rate
                        })
                
                # Sort cities by failure count (descending)
                city_failures.sort(key=lambda x: x["failed_count"], reverse=True)
                
                # Determine reliability bucket
                if pass_rate > 95:
                    reliability_bucket = '>95%'
                elif pass_rate >= 90:
                    reliability_bucket = '90-95%'
                elif pass_rate >= 80:
                    reliability_bucket = '80-90%'
                else:
                    reliability_bucket = '<80%'
                
                processed_data.append({
                    'test_uri': uri,
                    'pass_rate': pass_rate,
                    'passed_count': counts["passed"],
                    'total_count': counts["total"],
                    'reliability_bucket': reliability_bucket,
                    'city_failures': city_failures,
                    'blackbox_uri':counts['blackbox_uri']
                })
            
            # Sort by pass rate
            processed_data.sort(key=lambda x: x['pass_rate'])
            
            # Calculate bucket summary
            bucket_counter = Counter(item['reliability_bucket'] for item in processed_data)
            total_tests = len(processed_data)
            bucket_summary = []
            for bucket in ['>95%', '90-95%', '80-90%', '<80%']:
                count = bucket_counter.get(bucket, 0)
                percent = round((count / total_tests) * 100, 2) if total_tests else 0
                bucket_summary.append({
                    "range": bucket,
                    "count": count,
                    "percent": percent
                })
            
        except Exception as e:
            logger.error(f"Failed to run query: {e}")
            processed_data = []
            bucket_summary = []
            
        return render_template(
            'blackbox_data.html',
            lob=lob,
            data=processed_data,
            bucket_summary=bucket_summary,
            form=form
        )
        
    return render_template('blackbox_input.html', lob=lob, form=form)


@app.route('/bits', methods=['GET', 'POST'])
def bits():
    result_map = defaultdict(dict)
    form = dummyForm_to_skip_csrf()
    lob = request.args.get('lob') or request.form.get('lob') or 'money'

    if request.method == 'POST':
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            delta_days = (end_dt - start_dt).days

            if delta_days > 10:
                flash("Date range must not exceed 10 days.", "warning")
                return render_template('bits_input.html', lob=lob, form=form)

        except Exception as e:
            logger.error(f"Date parsing error: {e}")
            flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
            return render_template('bits_input.html', lob=lob, form=form)

        epic_name = EPIC_NAME_MAP.get(lob.lower(), 'BITS_E2E_Tests_Money')

        # Step 1: Get UUIDs from local SQLite table
        query = f"SELECT uri, uuid FROM {epic_name}"
        logger.debug(f"Query to get UUIDs: {query}")
        cursor.execute(query)
        test_rows = cursor.fetchall()
        test_uuids = [row[1] for row in test_rows]
        uuid_uri_map = {row[1]: row[0] for row in test_rows}

        if not test_uuids:
            logger.warning("No UUIDs found for selected LOB.")
            return render_template('bits_data.html', lob=lob, data=[], form=form)

        # Step 2: Format UUIDs for Presto IN clause
        uuid_in_clause = ",".join(f"'{uuid}'" for uuid in test_uuids)

        # Step 3: Execute Presto query
        presto_query = bits_optimized_query.format(
            start_date=start_date,
            end_date=end_date,
            uuid=uuid_in_clause
        )
        logger.debug(f"Presto query: {presto_query}")
        
        qr_client = Client(user_email='mkanna3@ext.uber.com')
        result = qr_client.execute('presto', presto_query)
        data = [row for row in result.fetchall()]

        # Step 4: Process each test result
        for row in data:
            uuid = row['testcase_uuid']
            status = row['status']
            
            if uuid not in result_map:
                result_map[uuid] = {
                    "test_uri": uuid_uri_map.get(uuid, uuid),
                    "total": 0,
                    "passed": 0,
                    "test_stability_type": row.get('test_stability_type', 'unknown'),
                    "stdout_uri": row.get('stdout_turi', ''),
                    "service_routing_health_level": row.get('service_routing_health_level', 0),
                    "tenancy": row.get('tenancy', '')
                }

            result_map[uuid]["total"] += 1
            if status == "passed":
                result_map[uuid]["passed"] += 1

        # Step 5: Calculate pass rates and assign reliability buckets
        for uuid, val in result_map.items():
            total = val["total"]
            passed = val["passed"]
            pass_rate = round((passed / total) * 100, 2) if total else 0

            # Assign reliability bucket
            if pass_rate > 95:
                reliability = ">95%"
            elif pass_rate >= 90:
                reliability = "90-95%"
            elif pass_rate >= 80:
                reliability = "80-90%"
            else:
                reliability = "<80%"

            val["pass_rate"] = pass_rate
            val["reliability_bucket"] = reliability

        # Step 6: Calculate bucket summary
        bucket_counter = Counter(val["reliability_bucket"] for val in result_map.values())
        total_tests = len(result_map)
        bucket_summary = []
        for bucket in ['>95%', '90-95%', '80-90%', '<80%']:
            count = bucket_counter.get(bucket, 0)
            percent = round((count / total_tests) * 100, 2) if total_tests else 0
            bucket_summary.append({
                "range": bucket,
                "count": count,
                "percent": percent
            })

        # Sort data by pass rate (descending)
        sorted_data = sorted(
            result_map.items(),
            key=lambda x: x[1]["pass_rate"]
        )

        return render_template(
            'bits_data.html',
            lob=lob,
            data=sorted_data,
            form=form,
            bucket_summary=bucket_summary
        )
    return render_template('bits_input.html', lob=lob, form=form)

@app.route('/unsound', methods=['GET', 'POST'])
def unsound():
    result_map = defaultdict(dict)
    form = dummyForm_to_skip_csrf_1()
    lob = request.args.get('lob') or request.form.get('lob') or 'money'

    if request.method == 'POST':
        lookback_days = request.form.get('lookback_days') or '3'
        epic_name = EPIC_NAME_MAP.get(lob.lower(), 'BITS_E2E_Tests_Money')

        logger.debug(f"Received form: lob={lob}, lookback_days={lookback_days}")
        
        # Step 1: Get UUIDs and URIs
        query = f"SELECT uri, uuid FROM {epic_name}"
        logger.debug(f"Query to get UUIDs: {query}")
        cursor.execute(query)
        test_rows = cursor.fetchall()
        test_uuids = [row[1] for row in test_rows]
        uuid_uri_map = {row[1]: row[0] for row in test_rows}

        if not test_uuids:
            logger.warning("No UUIDs found for selected LOB.")
            return render_template('unsound_data.html', lob=lob, data=[], form=form)

        uuid_in_clause = ",".join(f"'{uuid}'" for uuid in test_uuids)

        # Step 2: Presto query for unsound-specific results
    
        query = unsound_optimized_query.format(uuid=uuid_in_clause, lookback_days=lookback_days)
        logger.debug(f"Formatted unsound query: {query}")

        qr_client = Client(user_email='mkanna3@ext.uber.com')
        result = qr_client.execute('presto', query)
        data = [row for row in result.fetchall()]

        # Step 3: Aggregate unsound test stats
        for row in data:
            uuid = row['testcase_uuid']
            reliability = row.get('reliability_pct')
            stability = row.get('test_stability_type', 'unknown')

            if uuid not in result_map:
                result_map[uuid] = {
                    "reliability_scores": [],
                    "stability_type": stability
                }

            if reliability is not None:
                result_map[uuid]["reliability_scores"].append(reliability)


        # Step 4: Calculate pass rate and buckets
        for uuid, val in result_map.items():
            scores = val["reliability_scores"]
            avg_reliability = round(sum(scores) / len(scores), 2) if scores else 0

            if avg_reliability > 95:
                bucket = ">95%"
            elif avg_reliability >= 90:
                bucket = "90–95%"
            elif avg_reliability >= 80:
                bucket = "80–90%"
            else:
                bucket = "<80%"

            val["avg_reliability"] = avg_reliability
            val["reliability_bucket"] = bucket
            val["test_uri"] = uuid_uri_map.get(uuid, uuid)
        sorted_data = sorted(result_map.items(), key=lambda x: x[1]["avg_reliability"])
        return render_template('unsound_data.html', lob=lob, data=sorted_data, form=form)
    return render_template('unsound_input.html', lob=lob, form=form)



@app.route('/failing', methods=['GET', 'POST'])
def failing():
    form = dummyForm_to_skip_csrf_1()
    lob = request.args.get('lob') or request.form.get('lob') or 'unknown'
    if request.method == 'POST' and form.validate_on_submit():
        try:
            lookback_days = request.form.get('lookback_days', '3')
            logger.debug(f"Received form: lob={lob}, lookback_days={lookback_days}")
            if int(lookback_days) > 14:
                flash("Lookback days cannot be more than 14!", "warning")
                return render_template('failing_input.html', lob=lob, form=form)

            # Step 1: Get UUIDs and URIs
            epic_name = EPIC_NAME_MAP.get(lob.lower(), 'default')
            query = f"SELECT uri, uuid FROM {epic_name}"
            
            cursor.execute(query)
            test_rows = cursor.fetchall()
            test_uuids = [row[1] for row in test_rows]
            uuid_uri_map = {row[1]: row[0] for row in test_rows}

            if not test_uuids:
                logger.warning("No UUIDs found for selected LOB.")
                return render_template('unsound_data.html', lob=lob, data=[], form=form)

            uuid_in_clause = ",".join(f"'{uuid}'" for uuid in test_uuids)
            query = failing_optimized_query.format(uuid=uuid_in_clause, lookback_days=lookback_days)
            
            qr_client = Client(user_email='mkanna3@ext.uber.com')
            result = qr_client.execute('presto', query)
            raw_rows = [row for row in result.fetchall()]

            # Step 2: Aggregate by test UUID
            failure_map = defaultdict(list)
            for row in raw_rows:
                uuid = row.get('testcase_uuid')
                if uuid:
                    failure_map[uuid].append(row)

            final_data = []
            for uuid, rows in failure_map.items():
                # Get latest failure
                latest = sorted(rows, key=lambda r: r.get('datestr', ''), reverse=True)[0]
                raw_uri = uuid_uri_map.get(uuid, 'unknown')

                # Simple count by UUID
                failure_count = len(rows)

                # Process failed actions from test_scopes
                failed_action_counter = Counter()
                for row in rows:
                    scopes = row.get('test_scopes', '')
                    if scopes:
                        parts = scopes.split('\x02')
                        for part in parts:
                            if part.startswith('FAIL\x03test://'):
                                try:
                                    action_name = part.split('\x03')[1].split('/')[-1]
                                    failed_action_counter[action_name] += 1
                                except Exception as e:
                                    logger.warning(f"Failed to parse action from test_scope part: {part} - {e}")

                latest_data = {
                    'uri': raw_uri,
                    'failed_count': failure_count,  # Simple count by UUID
                    'latest_status': latest.get('status'),
                    'stability_type': latest.get('test_stability_type'),
                    'tenancy': latest.get('tenancy'),
                    'log_url': latest.get('stdout_turi'),
                    'stderr_turi': latest.get('stderr_turi'),
                    'failed_action': dict(failed_action_counter)  # Keep track of failed actions
                }

                # Debug logging
                logger.debug(f"Test: {raw_uri}")
                logger.debug(f"UUID: {uuid}")
                logger.debug(f"Failure count: {failure_count}")
                logger.debug(f"Failed actions: {dict(failed_action_counter)}")

                final_data.append(latest_data)

        except Exception as e:
            logger.error(f"Failed to run failing query: {e}")
            final_data = []
            
        final_data = sorted(final_data, key=lambda x: x['failed_count'], reverse=True)    
        return render_template('failing_data.html', lob=lob, data=final_data, form=form)

    return render_template('failing_input.html', lob=lob, form=form)


@app.route('/update', methods=['GET', 'POST'])
def update1():
    form = dummyForm_to_skip_csrf()
    lob = request.args.get('lob') or request.form.get('lob') or 'default'
    epic_name = EPIC_NAME_MAP.get(lob.lower(), 'default')
    if epic_name == 'default':
        flash("Invalid LOB selected.", "danger")
        return render_template('dashboard_money.html',lob='money', form=form)
    added_tests = []
    try:
        added_tests = update(epic_name)
    except Exception as e:
        logging.error(f"Failed to fetch testcases: {e}")
        flash("Failed to update test cases. Please try again later.", "danger")
        return render_template('dashboard_money.html',lob='money', form=form)
    flash(f"Successfully updated testcases. {len(added_tests)} new testcases added.", "success")
    return render_template('dashboard_money.html',lob='money', form=form)

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=5005,debug=True)