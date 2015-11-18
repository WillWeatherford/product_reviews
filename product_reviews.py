from amazonproduct.api import API
from bs4 import BeautifulSoup
import requests
import logging
import time
import csv
import os
import re

# from lxml import etree


# 1. use product api to get xml results for all products
# 2. find reviews iframe in XML
# 3. get url from iframe
# 4. get HTML with requests
# 5. scrape HTML for num reviews and rating
#       find('div', attrs={'class':'crIFrameNumCustReviews'})
# 6. export to CSV

# TODO

# get this list from command line input or file input instead
ASIN_LIST = [
    'B00W0I6TIM',
    'jdhdk$dm'
]

OUTPUT_CSV_PATH = os.path.join('./', 'product_reviews_data.csv')
LOGFILE_PATH = os.path.join('./', 'product_reviews.log')

ASIN = 'ASIN'
NUM_REVIEWS = 'Number of reviews'
AVG_SCORE = 'Average score'
FIELDNAMES = [ASIN, NUM_REVIEWS, AVG_SCORE]

API_DELAY = 2

DEFAULT_NAMESPACE = '{http://webservices.amazon.com/AWSECommerceService/2011-08-01}'
IFRAME_NAME = 'IFrameURL'
REVIEWS_DIV_CLASS = 'crIFrameNumCustReviews'

# Regular expressions for matching customer reviews data in HTML
NUM = r'\d{1,7}'
NUM_RE = re.compile(r'^' + NUM)
CUST = r'(\s[Cc]ustomer)?\s[Rr]eviews'
NUM_REVIEWS_RE = re.compile(r'^' + NUM + CUST + '$')
assert(NUM_REVIEWS_RE.match('223 customer reviews'))

FLOAT = r'[0-5]\.[0-9]'
FLOAT_RE = re.compile(r'^' + FLOAT)
WORDS = r'\s[Oo]ut\s[Oo]f\s5\s[Ss]tars'
AVG_SCORE_RE = re.compile(r'^' + FLOAT + WORDS + '$')
assert(AVG_SCORE_RE.match('4.8 out of 5 stars'))

# initialize logging tools
hn = logging.FileHandler(LOGFILE_PATH)
lg = logging.Logger('main_logger', level=logging.DEBUG)
lg.addHandler(hn)


def try_me(func):
    '''
    Simple decorator to wrap functions, reporting if they return nothing
    instead of something, or if they create an Exception.
    '''
    def try_(*args, **kwargs):
        result = None
        asin = kwargs.get('asin', '')
        func_name = func.__name__
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            lg.error('Error in {} for ASIN {}:\n{}'.format(func_name, asin, e),
                     exc_info=1)
        if not result:
            lg.error('No result from {} for ASIN {}'.format(func_name, asin),
                     exc_info=1)
        return result

    return try_


@try_me
def get_review_el(iframe, **kwargs):
    response = requests.get(iframe)
    soup = BeautifulSoup(response.text)
    return soup.find('div', class_=REVIEWS_DIV_CLASS)


@try_me
def get_num_reviews(reviews_el, **kwargs):
    reviews_link = reviews_el.find('a', text=NUM_REVIEWS_RE)
    text = reviews_link.text
    num_str = NUM_RE.match(text).group()
    return int(num_str)


@try_me
def get_avg_score(reviews_el, **kwargs):
    for attr in ('alt', 'title'):
        try:
            img = reviews_el.find('img', attrs={attr: FLOAT_RE})
            text = str(img.attrs[attr])
            avg_score_str = FLOAT_RE.match(text).group()
            return float(avg_score_str)
        except AttributeError:
            lg.error('No image element found with {} matching regex'
                     '{}'.format(attr, FLOAT_RE))
    return None


# can expand this into other API calls
@try_me
def get_reviews_iframe(asin=None):
    api = API(locale='us')
    xml = api.item_lookup(asin, ResponseGroup='Reviews')
    namespace = get_namespace(xml)
    iframe = xml.find('.//{}{}'.format(namespace, IFRAME_NAME))
    return iframe


@try_me
def get_namespace(xml):
    ns = xml.nsmap.get(None) or DEFAULT_NAMESPACE
    return '{' + ns + '}'


def write_to_csv(data, file_path):
    with open(file_path, 'w') as output_csv:
        writer = csv.DictWriter(output_csv, FIELDNAMES)
        writer.writerows(data)


def main(asin_data, output_csv_path):
    for row in asin_data:
        time.sleep(API_DELAY)
        asin = row['ASIN']

        iframe = get_reviews_iframe(asin=asin)
        if iframe:
            el = get_review_el(iframe, asin=asin)
            if el:
                num_reviews = get_num_reviews(el, asin=asin)
                avg_score = get_avg_score(el, asin=asin)
                row[NUM_REVIEWS] = num_reviews
                row[AVG_SCORE] = avg_score

    for row in asin_data:
        lg.info(', '.join(['{}: {}'.format(k, v) for k, v in row.items()]))

    write_to_csv(asin_data, output_csv_path)


if __name__ == '__main__':
    asin_list = ASIN_LIST
    asin_data = [{ASIN: n, NUM_REVIEWS: 0, AVG_SCORE: 0.0} for n in asin_list]
    output_csv_path = OUTPUT_CSV_PATH
    main(asin_data, output_csv_path)
