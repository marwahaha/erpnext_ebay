
from __future__ import unicode_literals
from __future__ import print_function


import __builtin__ as builtins


import sys
import os.path

sys.path.insert(0, "/usr/local/lib/python2.7/dist-packages/ebaysdk-2.1.4-py2.7.egg")
sys.path.insert(0, "/usr/local/lib/python2.7/dist-packages/lxml-3.6.4-py2.7-linux-i686.egg")
sys.path.insert(0, "/Library/Python/2.7/site-packages/ebaysdk-2.1.5-py2.7.egg")


import datetime
from types import MethodType
import string
import frappe
from frappe import msgprint,_
from frappe.utils import cstr

from ebaysdk.exception import ConnectionError
from ebaysdk.trading import Connection as Trading

# Need to add path to sites1.local where ebay.yaml resides
sys.path.insert(0, os.path.join(frappe.utils.get_bench_path(),'sites',frappe.get_site_path()))




@frappe.whitelist()
def generate_active_ebay_data():
    """Get all the active eBay listings and save them to table"""
    
    # set up the zEbayListings table
    create_ebay_listings_table()
    
    page = 1
    listings_dict = get_myebay_selling_request(page)
    pages = int(listings_dict['ActiveList']['PaginationResult']['TotalNumberOfPages'])
    #timestamp = listings_dict['Timestamp']
    
    while pages >= page:
        
        for item in listings_dict['ActiveList']['ItemArray']['Item']:
            ebay_id = item['ItemID']
            qty = int(item['QuantityAvailable'])
            try:
                sku = item['SKU']
            except:
                sku = ''
            #price = item['BuyItNowPrice']['value']
            #THSI IS 0        print(item['BuyItNowPrice']['value'])
            #Example: {'_currencyID': 'USD', 'value': '0.0'}   print(item['BuyItNowPrice'])
            curr_price = float(item['SellingStatus']['CurrentPrice']['value'])
            curr_ex_vat = curr_price / VAT
            currency = item['SellingStatus']['CurrentPrice']['_currencyID']  # or ['Currency']
            #converted_price = item['ListingDetails]['ConvertedBuyItNowPrice']['value']
            #description = item['Description']
            hit_count = 0 #int(item['HitCount'])
            watch_count = 0 #int(item['WatchCount'])
            question_count = 0 # int(item['TotalQuestionCount'])
            #title = item['Title']
            #conv_title = title.encode('ascii', 'ignore').decode('ascii')
            #new_title = MySQLdb.escape_string(conv_title)
            site = ''
            insert_ebay_listing(sku, ebay_id, qty, curr_ex_vat, site, hit_count, watch_count, question_count)
        
        page += 1
        if pages >= page:
            listings_dict = get_myebay_selling_request(page)
        else:
            break






def get_myebay_selling_request(page):
    
    # python -c "import certifi; print certifi.old_where()"
    #os.environ['REQUESTS_CA_BUNDLE'] = '/usr/local/lib/python2.7/dist-packages/certifi/cacert.pem'
    
    try:
        api_trading = Trading(config_file='ebay.yaml', warnings=True, timeout=20)
        
        #datetime.today().format('yyyy-mm-ddThh:mm:ss')
        
        api_request = {
        "ActiveList":{
            "Include": True,
            "Pagination": {
                "EntriesPerPage": 100,
                "PageNumber": page
            },
            "IncludeWatchCount": True
        },
        'DetailLevel': 'ReturnAll'
        }
        
        
        # activelist = api.execute('GetMyeBaySelling', {'ActiveList': True,'DetailLevel': 'ReturnAll','PageNumber': page})
        
        api_trading.execute('GetMyeBaySelling', api_request)
        products = api_trading.response.dict()

    
    except ConnectionError as e:
        print(e)
        print(e.response.dict())
        raise e
    
    return products







def create_ebay_listings_table():
    """Set up the zEbayListings table"""
    
    sql = """
        create table if not exists `zEbayListings` (
        `sku` varchar(20),
        `ebay_id` varchar(38),
        `qty` integer,
        `price` decimal(18,6),
        `site` varchar(6),
        `hit_count` integer,
        `watch_count` integer,
        `question_count` integer
        )
    """
    
    frappe.db.sql(sql, auto_commit = True)
    
    sql2 = """truncate table `zEbayListings` """
    
    frappe.db.sql(sql2, auto_commit = True)


def insert_ebay_listing(sku, ebay_id, qty, price,
                        site, hits, watches, questions):
    
    sql = """
    insert into `zEbayListings`
    values('{sku}', '{ebay_id}', {qty}, {price}, '{site}', {hit_count}, {watch_count}, {question_count})
    """.format(sku=sku, ebay_id=ebay_id, qty=qty, price=price, site=site,
               hit_count=hits, watch_count=watches, question_count=questions)
    
    
    frappe.db.sql(sql, auto_commit = True)
    







##########  EBAY ID SYNCING CODE ############
##########  EBAY ID SYNCING CODE ############
##########  EBAY ID SYNCING CODE ############
##########  EBAY ID SYNCING CODE ############
##########  EBAY ID SYNCING CODE ############



# if item is on ebay then set the ebay_id field
def set_item_ebay_id(item_code, ebay_id):
    """Given an item_code set the ebay_id field to the live eBay ID"""
    
    sql = """update `tabItem` it
            set it.ebay_id = '{}'
            where it.item_code = '{}' """.format(ebay_id, item_code)
    
    
    try:
        frappe.db.sql(sql, auto_commit = True)
    
    
    except Exception as inst:
        print("Unexpected error running ebay_id sync.", item_code)
        raise
        return False
    
    
    return True


def sync_ebay_ids():
    """Return only items that don't match"""
    
    sql = """
    select * from (
        SELECT t1.sku, t2.item_code, ifnull(t1.ebay_id, '') as live_ebay_id,
        ifnull(t2.ebay_id, '') as dead_ebay_id FROM `zEbayListings` t1
        LEFT JOIN `tabItem` t2 ON t1.sku = t2.item_code
        UNION
        SELECT t1.sku, t2.item_code, ifnull(t1.ebay_id, '') as live_ebay_id,
        ifnull(t2.ebay_id, '') as dead_ebay_id FROM `zEbayListings` t1
        RIGHT JOIN `tabItem` t2 ON t1.sku = t2.item_code
    ) as t
    where t.live_ebay_id <> t.dead_ebay_id
    """
    
    records = frappe.db.sql(sql, as_dict= True)

    
    for r in records:
        
        # If not live id then clear any value on system
        if r.live_ebay_id == '':
            set_item_ebay_id(r.item_code, '')
        else:
            # ok so item is live but id's don't match so update system with live version (but there must exist an item_code)
            if (r.item_code):
                set_item_ebay_id(r.sku, r.live_ebay_id)
            else:
                msgprint('The ebay item cannot be found on ERPNEXT so unable to record ebay id' + r.sku)






