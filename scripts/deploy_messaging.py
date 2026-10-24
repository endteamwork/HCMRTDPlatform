"""Create the Task 2 messaging layer: SNS FIFO topic, 3 SQS FIFO queues,
filtered subscriptions, and the S3 -> router Lambda notification.

Idempotent: safe to re-run. Usage: python scripts/deploy_messaging.py
"""

import json

import boto3

REGION = "eu-north-1"
ACCOUNT = "726701726833"
BUCKET = "data-hackathon-smit-ali"
TOPIC_NAME = "hcm-routed-events.fifo"
ROUTER_FN = "lambda_event_router"
SOURCES = {
    "jobs": "jobs-queue.fifo",
    "benchmarks": "benchmarks-queue.fifo",
    "fx": "fx-queue.fifo",
}

sns = boto3.client("sns", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)


def main():
    topic_arn = sns.create_topic(
        Name=TOPIC_NAME,
        Attributes={"FifoTopic": "true", "ContentBasedDeduplication": "false"},
    )["TopicArn"]
    print("topic:", topic_arn)

    for source, queue_name in SOURCES.items():
        queue_url = sqs.create_queue(
            QueueName=queue_name, Attributes={"FifoQueue": "true"}
        )["QueueUrl"]
        queue_arn = sqs.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]

        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "AllowSnsDelivery",
                    "Effect": "Allow",
                    "Principal": {"Service": "sns.amazonaws.com"},
                    "Action": "sqs:SendMessage",
                    "Resource": queue_arn,
                    "Condition": {"ArnEquals": {"aws:SourceArn": topic_arn}},
                }
            ],
        }
        sqs.set_queue_attributes(
            QueueUrl=queue_url, Attributes={"Policy": json.dumps(policy)}
        )

        sub_arn = sns.subscribe(
            TopicArn=topic_arn,
            Protocol="sqs",
            Endpoint=queue_arn,
            Attributes={
                "FilterPolicy": json.dumps({"source": [source]}),
                "RawMessageDelivery": "true",
            },
            ReturnSubscriptionArn=True,
        )["SubscriptionArn"]
        print(f"queue {queue_name} subscribed ({source}): {sub_arn}")

    # S3 ObjectCreated on raw/ -> router Lambda
    fn_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{ROUTER_FN}"
    try:
        lam.add_permission(
            FunctionName=ROUTER_FN,
            StatementId="allow-s3-raw-events",
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=f"arn:aws:s3:::{BUCKET}",
            SourceAccount=ACCOUNT,
        )
    except lam.exceptions.ResourceConflictException:
        pass

    s3.put_bucket_notification_configuration(
        Bucket=BUCKET,
        NotificationConfiguration={
            "LambdaFunctionConfigurations": [
                {
                    "Id": "raw-to-router",
                    "LambdaFunctionArn": fn_arn,
                    "Events": ["s3:ObjectCreated:*"],
                    "Filter": {
                        "Key": {
                            "FilterRules": [{"Name": "prefix", "Value": "raw/"}]
                        }
                    },
                }
            ]
        },
    )
    print("S3 notification raw/ ->", ROUTER_FN)


if __name__ == "__main__":
    main()
