from ml_api import call_ops_ml_api, call_security_ml_api
from correlation import correlation_pipeline


def process_log(log, log_type):

    ops_result = None
    sec_result = None

    if log_type == "ops":
        ops_result = call_ops_ml_api(log)

    elif log_type == "security":
        sec_result = call_security_ml_api(log)

    elif log_type == "both":
        ops_result = call_ops_ml_api(log["ops"])
        sec_result = call_security_ml_api(log["security"])

    return correlation_pipeline(
        raw_ops=ops_result,
        raw_security=sec_result
    )

