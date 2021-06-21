from boto3.session import Session
import boto3
import requests
import yaml
import tempfile
from os import path, listdir, getenv
import tarfile
import subprocess
import sys
import logging
from time import sleep


S3_URL_FORMAT = "https://{bucket}.s3.amazonaws.com"


def get_index_yaml(bucket: str, key: str):
    url = S3_URL_FORMAT.format(bucket=bucket)
    url = path.join(url, key, 'index.yaml')
    r = requests.get(url)
    r.raise_for_status()
    return yaml.load(r.text, Loader=yaml.SafeLoader)


def remove_chart_entry(index_yaml: str, chart_name: str, chart_version: str):
    logging.debug(f'Removing {chart_name}-{chart_version} from index')
    chart_data = []
    for chart in index_yaml.get('entries', {}).get(chart_name, []):
        if chart.get('name') != chart_name or chart.get('version') != chart_version:
            chart_data.append(chart)
    index_yaml['entries'][chart_name] = chart_data
    return index_yaml


def download_archive(url, file_name):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(file_name, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def add_chart_entries(bucket, repo_key, keys, index_yaml):
    with tempfile.TemporaryDirectory() as tmpdirname:
        for key in keys:
            logging.debug(f'Adding {key} to index')
            url = S3_URL_FORMAT.format(bucket=bucket)
            url = f"{url}/{key}"
            archive = "{}/{}".format(tmpdirname, path.basename(key))
            download_archive(url, archive)
        tmp_index_file = path.join(tmpdirname, 'oldindex.yaml')
        with open(tmp_index_file, 'w') as f:
            yaml.dump(index_yaml, f, default_flow_style=False)
        repo_url = '{}/{}'.format(S3_URL_FORMAT.format(bucket=bucket), repo_key)
        subprocess.run(['helm', 'repo', 'index', tmpdirname, '--merge', tmp_index_file, '--url', repo_url], check=True)
        with open(path.join(tmpdirname, 'index.yaml'), 'r') as f:
            index_yaml = yaml.load(f.read(), Loader=yaml.SafeLoader)
    return index_yaml


def get_env_or_die(key):
    val = getenv(key)
    if val is None or val == '':
        logging.error(f'Must supply {key} in environment')
        sys.exit(1)
    return val


def main():
    access_key = get_env_or_die('ACCESS_KEY')
    secret_key = get_env_or_die('SECRET_KEY')
    bucket = get_env_or_die('S3_BUCKET')
    s3_key = path.join(get_env_or_die('S3_KEY'), "")

    if getenv('LOG_LEVEL') == 'debug':
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    logging.info(f"Beginning to index charts at s3://{bucket}/{s3_key}")

    while True:
        s3_client = boto3.client('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        index_yaml = get_index_yaml(bucket, s3_key)
        indexed_chart_set = set()
        indexed_charts = {}
        for cn, charts in index_yaml.get('entries', {}).items():
            for chart in charts:
                chart_name = chart.get('name')
                chart_version = chart.get('version')
                if chart_name is None or chart_version is None:
                    continue
                s3_chart_key = path.join(s3_key, f"{chart_name}-{chart_version}.tgz")
                indexed_charts[s3_chart_key] = chart
        s3_chart_set = set()
        has_all_objects = False
        next_token = None
        while not has_all_objects:
            if next_token is not None:
                repo_objects = s3_client.list_objects_v2(Prefix=s3_key, Bucket=bucket, ContinuationToken=next_token)
            else:
                repo_objects = s3_client.list_objects_v2(Prefix=s3_key, Bucket=bucket)
            has_all_objects = (not repo_objects['IsTruncated'])
            next_token = repo_objects.get('NextContinuationToken')
            for content in repo_objects['Contents']:
                # datetime.datetime
                last_modified = content['LastModified']
                # emissary-ingress/ambassador-6.7.7-ci.105.tgz
                key = content['Key']
                # just ignore anything that isnt' a zip file
                if not key.endswith('.tgz'):
                    continue
                s3_chart_set.add(key)
        indexed_chart_set = set(indexed_charts.keys())
        to_delete = indexed_chart_set.difference(s3_chart_set)
        to_add = s3_chart_set.difference(indexed_chart_set)
        logging.info("Adding {} charts and removing {} charts".format(len(to_add), len(to_delete)))
        for k in to_delete:
            index_yaml = remove_chart_entry(index_yaml, indexed_charts[k]['name'], indexed_charts[k]['version'])
        if len(to_add) > 0:
            index_yaml = add_chart_entries(bucket, s3_key, to_add, index_yaml)
        index_yaml_bytes = yaml.dump(index_yaml, default_flow_style=False)
        s3_client.put_object(Body=index_yaml_bytes, Bucket=bucket, Key=path.join(s3_key, 'index.yaml'))
        logging.info(f"Finished indexing helm charts for {bucket}/{s3_key}")
        logging.debug(f"Sleeping 5 seconds")
        sleep(5)


if __name__ == '__main__':
    main()
