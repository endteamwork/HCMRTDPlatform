import importlib.util
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

REGION = "eu-north-1"
BUCKET = "data-hackathon-smit-ali"


def load_handler(lambda_name):
    """Import src/lambdas/<name>/handler.py under a unique module name."""
    path = SRC / "lambdas" / lambda_name / "handler.py"
    spec = importlib.util.spec_from_file_location(f"{lambda_name}_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def aws_s3():
    """Mocked S3 with the hackathon bucket created."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = REGION
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        yield s3
