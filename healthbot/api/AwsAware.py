#!/usr/bin/env python3

# Standard imports

import boto3
from boto3 import client


class AwsAware:
    def __init__(self, aws_profile: str = None) -> None:
        """
        Helper to get a given AWS Client
        """
        if aws_profile is not None:
            session = boto3.Session(profile_name=aws_profile)
            self.client = session.client(service_name=self.service_code)
        else:
            self.client = boto3.client(service_name=self.service_code)

    def get_aws_client(self) -> client:

        return self.client
