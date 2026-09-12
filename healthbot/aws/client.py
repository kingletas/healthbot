"""The boto3 client a check or a sender talks to, built once per instance."""

import boto3


class AwsClient:
    """Base for anything that calls one AWS service. Subclasses set service_code."""

    service_code: str

    def __init__(self, aws_profile: str | None = None) -> None:
        if aws_profile is not None:
            session = boto3.Session(profile_name=aws_profile)
            self.client = session.client(service_name=self.service_code)
        else:
            self.client = boto3.client(service_name=self.service_code)
