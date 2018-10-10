# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import boto3
import json
import os
import random
import resource_tools
import string
import time
from subprocess import call

WEB_FOLDER = "/tmp/msam"


def lambda_handler(event, context):
    """
    Lambda entry point. Print the event first.
    """
    print("Event Input: %s" % json.dumps(event))
    bucket_name = event["ResourceProperties"]["BucketName"]
    result = {
        'Status': 'SUCCESS',
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        'Data': {},
        'ResourceId': bucket_name
    }

    if event.get("PhysicalResourceId", False):
        result["PhysicalResourceId"] = event["PhysicalResourceId"]
    else:
        result["PhysicalResourceId"] = "{}-{}".format(
            resource_tools.stack_name(event), event["LogicalResourceId"])

    try:
        if event["RequestType"] == "Create" or event["RequestType"] == "Update":
            print(event["RequestType"])
            replace_bucket_contents(bucket_name)
        elif event["RequestType"] == "Delete":
            print(event["RequestType"])
            delete_bucket_contents(bucket_name)
    except Exception as exp:
        print("Exception: %s" % exp)
        result = {
            'Status': 'FAILED',
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            'Data': {"Exception": str(exp)},
            'ResourceId': None
        }
    resource_tools.send(
        event,
        context,
        result['Status'],
        result['Data'],
        result["PhysicalResourceId"])
    return


def replace_bucket_contents(bucket_name):
    client = boto3.client("s3")
    source = "https://rodeolabz-{region}.s3.amazonaws.com/msam/msam-web.zip".format(
        region=os.environ["AWS_REGION"])

    # empty the bucket
    delete_bucket_contents(bucket_name)

    # execute these commands to download the zip and extract it locally
    command_list = [
        "rm -f /tmp/msam-web.zip",
        "rm -rf {}".format(WEB_FOLDER),
        "curl --silent -o /tmp/msam-web.zip {url}".format(url=source),
        "mkdir {}".format(WEB_FOLDER),
        "unzip /tmp/msam-web.zip -d {}".format(WEB_FOLDER),
        "ls -l {}".format(WEB_FOLDER)
    ]
    for command in command_list:
        print(call(command, shell=True))

    # upload each local file to the bucket, preserve folders
    for dirpath, dirnames, filenames in os.walk(WEB_FOLDER):
        for name in filenames:
            local = "{}/{}".format(dirpath, name)
            remote = local.replace("{}/".format(WEB_FOLDER), "")
            content_type = None
            if remote.endswith(".js"):
                content_type = "application/javascript"
            elif remote.endswith(".html"):
                content_type = "text/html"
            else:
                content_type = "binary/octet-stream"
            client.put_object(Bucket=bucket_name, Key=remote,
                              Body=open(local, 'rb'), ContentType=content_type)
    return


def delete_bucket_contents(bucket_name):
    # empty the bucket
    client = boto3.client("s3")
    response = client.list_objects_v2(
        Bucket=bucket_name
    )
    if "Contents" in response:
        for item in response["Contents"]:
            client.delete_object(Bucket=bucket_name, Key=item["Key"])
    return
