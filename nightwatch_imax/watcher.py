# -*- coding: utf-8 -*-
import logging
import re
import os

import boto3
import arrow
import requests
from bs4 import BeautifulSoup

MOVIE_CODE_PATTERN = re.compile("popupSchedule\('.*','.*','(\d\d:\d\d)','\d*','\d*', '(\d*)', '\d*', '\d*',")


def is_cgv_online():
    try:
        health_check = requests.get('http://m.cgv.co.kr')
        return health_check.status_code == 200
    except Exception as e:
        logger.error(e)
        return False


def get_date_list(theater_code):
    today = arrow.now('Asia/Seoul').format('YYYYMMDD')

    date_list_url = 'http://m.cgv.co.kr/Schedule/?tc={}&t=T&ymd={}&src='.format(theater_code, today)
    date_list_response = requests.get(date_list_url).text

    date_list_pattern = re.compile('var ScheduleDateData = \[(.*)\]', re.MULTILINE)
    date_list = date_list_pattern.search(date_list_response).group(1).encode().decode('unicode-escape')

    date_pattern = re.compile('getMovieSchedule\(\'(\d{8})\',')
    dates = date_pattern.findall(date_list)

    return dates


def get_schedule_list(theater_code, date):
    schedule_url = 'http://m.cgv.co.kr/Schedule/cont/ajaxMovieSchedule.aspx'
    schedule_response = requests.post(schedule_url, data={'theaterCd': theater_code, 'playYMD': date}).text
    soup = BeautifulSoup(schedule_response, 'html.parser')

    schedule_list = []

    for time_list in soup.find_all('ul', 'timelist'):
        schedule_list.extend(time_list.find_all('li'))

    return schedule_list


def get_schedule_info(schedule_str):
    return MOVIE_CODE_PATTERN.search(schedule_str)


def save(theater_code, date, schedule_list):
    created_at = arrow.utcnow().timestamp

    with table.batch_writer(overwrite_by_pkeys=['id', 'created_at']) as batch:
        for schedule in schedule_list:
            raw_data = str(schedule)

            schedule_info = get_schedule_info(raw_data)

            if schedule_info is None:
                logger.warning('Missing schedule_info : %s', raw_data)
                continue

            time = schedule_info.group(1).replace(':', '')
            movie_code = schedule_info.group(2)

            raw_data_id = '{}.{}.{}.{}'.format(theater_code, date, movie_code, time)

            batch.put_item(Item={'id': raw_data_id,
                                 'created_at': created_at,
                                 'raw_data': raw_data,
                                 'theater_code': theater_code,
                                 'date': date,
                                 'movie_code': movie_code,
                                 'time': time})

            logger.info('Saved : %s', raw_data_id)


def watcher_lambda_handler(event, context):
    if not is_cgv_online():
        raise Exception('Cannot connect CGV server!')

    theater_code = os.environ['theater_code']

    for date in get_date_list(theater_code):
        schedule_list = get_schedule_list(theater_code, date)

        save(theater_code, date, schedule_list)

    return theater_code


logger = logging.getLogger()
table = boto3.resource('dynamodb').Table('nightwatch-imax-raw-data')
