import boto3
import requests
from os import path, listdir, getenv, makedirs, remove
import subprocess
import sys
import logging
from time import sleep


S3_URL_FORMAT = "https://{bucket}.s3.amazonaws.com"


def remove_stale_charts(directory, s3_key, s3_chart_set):
    chart_dir = path.join(directory, s3_key)

    archive_files= [f for f in listdir(chart_dir) if path.isfile(path.join(chart_dir, f))]
    for f in archive_files:
        if path.join(s3_key, f) not in s3_chart_set:
            remove(path.join(chart_dir, f))


def download_archive(url, file_name):
    if not path.isdir(path.dirname(file_name)):
        makedirs(path.dirname(file_name))

    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(file_name, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


def index_charts(directory, bucket, s3_key):
    index_file = path.join(directory, s3_key, 'index.yaml')
    repo_url = '{}/{}'.format(S3_URL_FORMAT.format(bucket=bucket), s3_key)
    subprocess.run(['helm', 'repo', 'index', path.join(directory, s3_key), '--url', repo_url], check=True)

    return index_file


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

    log_format = '%(asctime)s | %(levelname)s | %(message)s'
    if getenv('LOG_LEVEL') == 'debug':
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG, format=log_format)
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format=log_format)

    logging.info(f"Beginning to index charts at s3://{bucket}/{s3_key}")
    directory = getenv('CHART_ARCHIVE_DIRECTORY')
    if directory == '' or directory is None:
        directory = tempfile.mkdtemp()
    if not path.isdir(directory):
        makedirs(directory)
    directory = path.abspath(directory)

    while True:
        s3_client = boto3.client('s3', aws_access_key_id=access_key, aws_secret_access_key=secret_key)
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
                # emissary-ingress/ambassador-6.7.7-ci.105.tgz
                key = content['Key']
                # just ignore anything that isnt' a zip file
                if not key.endswith('.tgz'):
                    continue
                file_path = path.join(directory, key)
                if not path.isfile(file_path):
                    url = S3_URL_FORMAT.format(bucket=bucket)
                    url = f"{url}/{key}"
                    download_archive(url, file_path)

                s3_chart_set.add(key)
        remove_stale_charts(directory, s3_key, s3_chart_set)
        index_file = index_charts(directory, bucket, s3_key)
        s3_client.put_object(Body=index_file, Bucket=bucket, Key=path.join(s3_key, 'index.yaml'))
        logging.info(f"Finished indexing helm charts for {bucket}/{s3_key}")
        logging.debug(f"Sleeping 5 seconds")
        sleep(5)


if __name__ == '__main__':
    main()
