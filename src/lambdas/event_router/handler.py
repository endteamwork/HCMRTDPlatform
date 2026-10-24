"""lambda_event_router: triggered by S3 ObjectCreated events on raw/.

Reads the source from the object's metadata contract and republishes the
event to the SNS FIFO topic hcm-routed-events.fifo with a `source` message
attribute, so SNS filter policies deliver it to the right FIFO queue.

Env vars:
    TOPIC_ARN   ARN of hcm-routed-events.fifo
"""

import hashlib
import json
import os
import urllib.parse

import boto3

s3 = boto3.client("s3")
sns = boto3.client("sns")


def lambda_handler(event, context):
    topic_arn = os.environ["TOPIC_ARN"]
    routed = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        etag = record["s3"]["object"].get("eTag", "")

        head = s3.head_object(Bucket=bucket, Key=key)
        contract = head.get("Metadata", {})
        source = contract.get("source")
        if not source:
            # Fall back to the key layout raw/{source}/...
            parts = key.split("/")
            source = parts[1] if len(parts) > 1 else "unknown"

        message = {
            "bucket": bucket,
            "key": key,
            "source": source,
            "contract": contract,
        }
        dedup_id = hashlib.sha256(f"{key}:{etag}".encode()).hexdigest()

        sns.publish(
            TopicArn=topic_arn,
            Message=json.dumps(message),
            MessageAttributes={
                "source": {"DataType": "String", "StringValue": source}
            },
            MessageGroupId=source,
            MessageDeduplicationId=dedup_id,
        )
        routed.append({"key": key, "source": source})

    return {"statusCode": 200, "routed": routed}
