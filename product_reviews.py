from amazonproduct.api import API, InvalidSignature, InvalidClientTokenId
from bs4 import BeautifulSoup
import requests
import logging
import time
import json
import csv
import sys
import os
import re

# 1. use product api to get xml results for all products
# 2. find reviews iframe in XML
# 3. get url from iframe
# 4. get HTML with requests
# 5. scrape HTML for num reviews and rating
#       find('div', attrs={'class':'crIFrameNumCustReviews'})
# 6. print to console as JSON

# TODO
# time stamps in log
# file input
# use argparse for more sophisticated use of command line args and flags?

ASIN_LIST = []

LOGFILE_PATH = os.path.join('./', 'product_reviews.log')
CONFIG_FILE_PATH = os.path.join('./', '.amazon-product-api')
OUTPUT_CSV_PATH = os.path.join('./', 'product_reviews_data.csv')

ASIN = 'ASIN'
NUM_REVIEWS = 'Number of reviews'
AVG_SCORE = 'Average score'
FIELDNAMES = [ASIN, NUM_REVIEWS, AVG_SCORE]

API_DELAY = 2
REQUEST_DELAY = 5
TIMEOUT = 10
REQUEST_ATTEMPTS = 10

DEFAULT_NAMESPACE = '{http://webservices.amazon.com/AWSECommerceService/2011-08-01}'
IFRAME_NAME = 'IFrameURL'
REVIEWS_DIV_CLASS = 'crIFrameNumCustReviews'

# Regular expressions for matching customer reviews data in HTML
NUM = r'\d{1,7}'
NUM_RE = re.compile(r'^' + NUM)
CUST = r'(\s[Cc]ustomer)?\s[Rr]eview(s)?'
NUM_REVIEWS_RE = re.compile(r'^' + NUM + CUST + '$')
assert(NUM_REVIEWS_RE.match('223 customer reviews'))
assert(NUM_REVIEWS_RE.match('0 Customer Reviews'))
assert(NUM_REVIEWS_RE.match('1 Review'))

FLOAT = r'[0-5]\.[0-9]'
FLOAT_RE = re.compile(r'^' + FLOAT)
WORDS = r'\s[Oo]ut\s[Oo]f\s5(\s[Ss]tars)?'
AVG_SCORE_RE = re.compile(r'^' + FLOAT + WORDS + '$')
assert(AVG_SCORE_RE.match('4.8 out of 5 stars'))
assert(AVG_SCORE_RE.match('4.8 Out Of 5 Stars'))
assert(AVG_SCORE_RE.match('0.0 out of 5'))

# Initialize logging tools
logging_format = '%(levelname)s: %(message)s'
fr = logging.Formatter(logging_format)
hn = logging.FileHandler(LOGFILE_PATH)
lg = logging.Logger('main_logger', level=logging.DEBUG)
hn.setFormatter(fr)
lg.addHandler(hn)


def try_me(func):
    '''
    Simple decorator to wrap functions, reporting if they return nothing
    instead of something, or if they create an Exception.
    '''
    def try_(*args, **kwargs):
        result = None
        asin = kwargs.get('asin', '')
        api = kwargs.get('api', None)
        func_name = func.__name__
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            lg.error('Error in {} for ASIN {}:\n\t{}'.format(func_name, asin, e))
            if api:
                if isinstance(e, InvalidClientTokenId):
                    lg.info('Used Access Key: {}'.format(api.access_key))
                if isinstance(e, InvalidSignature):
                    lg.info('Used Secret Key: {}'.format(api.secret_key))
        if not result:
            lg.error('No result from {} for ASIN {}'.format(func_name, asin))
        return result
    return try_


# can expand this into other API calls
@try_me
def get_reviews_iframe(asin=None, api=None):
    '''
    Takes the ASIN for a product, queries the amazonproduct API to get an XML
    object, then returns the Product Reviews iframe URL from the XML.
    e.g.
    'A000H4F12' -> 'https://...'
    '''
    xml = api.item_lookup(asin, ResponseGroup='Reviews')
    namespace = get_namespace(xml)
    iframe = xml.find('.//{}{}'.format(namespace, IFRAME_NAME))
    return iframe


@try_me
def get_namespace(xml):
    '''
    Gets the "namespace" from the nsmap field of an XML object. This is
    necessary to accurately find specific tags within the XML.
    e.g.
    <lxml.objecify> -> '{https://...}
    '''
    ns = xml.nsmap.get(None) or DEFAULT_NAMESPACE
    return '{' + ns + '}'


@try_me
def get_review_el(url, **kwargs):
    '''
    Takes a string argument (the url for an Amazon Product Reviews iframe),
    gets HTML response from that url and returns a BeautifulSoup Element
    instance of the div tag containing the number and average rating of
    the reviews.
    e.g.
    'https://...' -> <div class='crIFrameNumCustReviews' ...>...</div>
    '''
    attempts = 0
    while attempts <= REQUEST_ATTEMPTS:
        try:
            response = requests.get(url, timeout=TIMEOUT)
            break
        except requests.exceptions.RequestException as e:
            attempts += 1
            if attempts > REQUEST_ATTEMPTS:
                raise e
            time.sleep(REQUEST_DELAY)
    soup = BeautifulSoup(response.text, 'lxml')
    return soup.find('div', class_=REVIEWS_DIV_CLASS)


@try_me
def get_num_reviews(reviews_el, **kwargs):
    '''
    Takes a BeautifulSoup Element instance and returns an integer of the
    number of reviews of the product found in HTML.
    e.g.
    <div class='crIFrameNumCustReviews' ...>...</div> -> 223
    '''
    reviews_link = reviews_el.find('a', text=NUM_REVIEWS_RE)
    text = reviews_link.text
    num_str = NUM_RE.match(text).group()
    return int(num_str)


@try_me
def get_avg_score(reviews_el, **kwargs):
    '''
    Takes a BeautifulSoup Element instance and returns a float of the
    average score of reviews of the product found in HTML.
    e.g.
    <div class='crIFrameNumCustReviews' ...>...</div> -> 4.8
    '''
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


def write_to_csv(data, file_path):
    '''
    Writes customer reviews data to a CSV document, using the FIELDNAMES
    constant as column headers.
    '''
    with open(file_path, 'w') as output_csv:
        writer = csv.DictWriter(output_csv, FIELDNAMES)
        writer.writerows(data)


def output_json(data, out):
    '''
    Write JSON to a given "file-like" object. Default is sys.stdout, which
    print to the console.
    '''
    j = '{}\n'.format(json.dumps(data))
    out.write(j)


def main(asin_list, cfg, out):
    '''
    Main function. Loops through all given ASINs and finds review data for each
    individually.
    Outputs to command line stream with stdout, or saves to csv document.
    '''
    asin_data = []
    api = API(cfg=cfg, locale='us')
    for asin in asin_list:
        time.sleep(API_DELAY)

        iframe = get_reviews_iframe(asin=asin, api=api)
        if iframe:
            el = get_review_el(iframe, asin=asin)
            if el:
                num_reviews = get_num_reviews(el, asin=asin)
                avg_score = get_avg_score(el, asin=asin)

                if all((asin, num_reviews, avg_score)):
                    row = {ASIN: asin,
                           NUM_REVIEWS: num_reviews,
                           AVG_SCORE: avg_score}
                    asin_data.append(row)

    output_json(asin_data, out)
    # write_to_csv(asin_data, out)


if __name__ == '__main__':
    lg.info('--------------PROCESS STARTED--------------\n')
    try:
        arg1 = sys.argv[1]
        asin_list = json.loads(arg1)
    except IndexError:
        # raise IndexError('Expected argument: list of ASINs in JSON array or file.')
        asin_list = ASIN_LIST
    try:
        arg2 = sys.argv[2]
        cfg = json.loads(arg2)
    except IndexError:
        cfg = CONFIG_FILE_PATH
    try:
        out = sys.argv[3]
    except IndexError:
        out = sys.stdout
    main(asin_list, cfg, out)
