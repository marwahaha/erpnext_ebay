"""Functions to retrieve data from eBay via ebaysdk module and TradingAPI."""

from __future__ import unicode_literals
from __future__ import print_function

import collections
import os
import sys
import operator

import frappe
from frappe import _, msgprint

from ebaysdk.exception import ConnectionError
from ebaysdk.trading import Connection as Trading


siteid = 3  # eBay site id: 0=US, 3=UK


def get_orders():
    """Returns a list of recent orders from the Ebay TradingAPI."""

    orders = None
    ebay_customers = []

    orders = []
    page = 1
    num_days = frappe.db.get_value(
        'eBay Manager Settings', filters=None, fieldname='ebay_sync_days')
    try:
        if num_days < 1:
            msgprint('Invalid number of days: ' + str(num_days))
    except TypeError:
        raise ValueError('Invalid type in ebay_sync_days')

    try:
        # Initialize TradingAPI; default timeout is 20.
        api = Trading(config_file='ebay.yaml', siteid=siteid,
                      warnings=True, timeout=20)

    except ConnectionError as e:
        print(e)
        print(e.response.dict())
        raise e

    while True:
        # TradingAPI results are paginated, so loop until
        # all pages have been obtained
        try:
            api.execute('GetOrders', {'NumberOfDays': num_days,
                                      'Pagination': {'EntriesPerPage': 100,
                                                     'PageNumber': page}})
        except ConnectionError as e:
            print(e)
            print(e.response.dict())
            raise e

        orders_api = api.response.dict()

        if int(orders_api['ReturnedOrderCountActual']) > 0:
            orders.extend(orders_api['OrderArray']['Order'])
        if orders_api['HasMoreOrders'] == 'false':
            break
        page += 1

    return orders, num_days


def get_categories_versions():
    """Load the version number of the current eBay categories
    and category features.
    """

    try:
        # Initialize TradingAPI; default timeout is 20.
        api = Trading(domain='api.sandbox.ebay.com', config_file='ebay.yaml',
                      siteid=siteid, warnings=True, timeout=20)

        response1 = api.execute('GetCategories', {'LevelLimit': 1,
                                                  'ViewAllNodes': False})

        response2 = api.execute('GetCategoryFeatures', {})

    except ConnectionError as e:
        print(e)
        print(e.response.dict())
        raise e

    categories_version = response1.reply.CategoryVersion
    features_version = response2.reply.CategoryVersion

    return (categories_version, features_version)


def get_categories():
    """Load the eBay categories for the categories cache."""

    try:
        # Initialize TradingAPI; default timeout is 20.
        api = Trading(domain='api.sandbox.ebay.com', config_file='ebay.yaml',
                      siteid=siteid, warnings=True, timeout=60)

        response = api.execute('GetCategories', {'DetailLevel': 'ReturnAll',
                                                 'ViewAllNodes': True})

    except ConnectionError as e:
        print(e)
        print(e.response.dict())
        raise e

    categories_data = response.dict()

    # Process the remaining categories data
    cl = categories_data['CategoryArray']['Category']
    # Use one dictionary element per level, to store each Category against its
    # CategoryID. For simplicity don't use the first [0] level as CategoryLevel
    # is one-indexed.
    levels = []
    for cat in cl:
        cat['Children'] = []
        cat_level = int(cat['CategoryLevel'])
        while cat_level > len(levels)-1:
            levels.append({})
        # Add the category to the relevant level dictionary
        levels[cat_level][cat['CategoryID']] = cat

    max_level = len(levels) - 1

    # Loop over all deeper levels; connect categories to their parents
    for parent_level, level_dict in enumerate(levels[2:], start=1):
        for cat in level_dict.values():
            parent = levels[parent_level][cat['CategoryParentID']]
            parent['Children'].append(cat)

    # Sort the Children list of each category according to its CategoryName
    for cat in cl:
        cat['Children'].sort(key=operator.itemgetter('CategoryName'))

    # Sort the top level list according to the CategoryName of the categories
    top_level = levels[1].values()
    top_level.sort(key=operator.itemgetter('CategoryName'))

    categories_data['TopLevel'] = top_level

    del categories_data['CategoryArray']

    # Return the new categories
    return categories_data, max_level


def get_features():
    """Load the eBay category features for the features cache."""

    try:
        # Initialize TradingAPI; default timeout is 20.
        api = Trading(domain='api.sandbox.ebay.com', config_file='ebay.yaml',
                      siteid=siteid, warnings=True, timeout=60)

    except ConnectionError as e:
        print(e)
        print(e.response.dict())
        raise e

    features_data = None
    feature_definitions = set()
    listing_durations = {}

    # Loop over each top-level category, pulling in all of the data
    search_categories = frappe.db.sql("""
        SELECT CategoryID, CategoryName, CategoryLevel
        FROM eBay_categories_hierarchy WHERE CategoryParentID=0
        """, as_dict=True)

    # BEGIN DUBIOUS WORKAROUND
    # Even some top-level categories have a habit of timing out
    # Run over their subcategories instead
    problematic_categories = ['1']  # Categories that timeout
    problem_parents = []
    problem_children = []
    for category in search_categories:
        category_id = category['CategoryID']
        if category_id in problematic_categories:
            problem_parents.append(category)
            children = frappe.db.sql("""
                SELECT CategoryID, CategoryName, CategoryLevel
                FROM eBay_categories_hierarchy WHERE CategoryParentID=%s
                """, (category_id,), as_dict=True)
            problem_children.extend(children)
    for parent in problem_parents:
        search_categories.remove(parent)
    search_categories.extend(problem_children)
    search_categories.extend(problem_parents)  # Now at end of list
    # END DUBIOUS WORKAROUND

    for category in search_categories:
        category_id = category['CategoryID']
        category_level = int(category['CategoryLevel'])
        sub_string = 'sub' * (category_level-1)
        print('Loading for {}category {}...'.format(sub_string,
                                                    category_id))
        options = {'CategoryID': category_id,
                   'DetailLevel': 'ReturnAll',
                   'ViewAllNodes': True}
        # BEGIN DUBIOUS WORKAROUND
        # Only look at the top level for this category
        if category_id in problematic_categories:
            options['LevelLimit'] = 1
        # END DUBIOUS WORKAROUND

        try:
            response = api.execute('GetCategoryFeatures', options)
        except ConnectionError as e:
            print(e)
            print(e.response.dict())
            raise e
        response_dict = response.dict()

        if features_data is None:
            # First batch of new categories
            features_data = response_dict   # Initialize with the whole dataset
            # Extract all the FeatureDefinition keys
            feature_definitions.update(
                features_data['FeatureDefinitions'].keys())
            # Special-case the ListingDurations
            lds = response_dict['FeatureDefinitions']['ListingDurations']
            features_data['ListingDurationsVersion'] = lds['_Version']
            if 'ListingDuration' in lds:
                for ld in lds['ListingDuration']:
                    listing_durations[ld['_durationSetID']] = ld['Duration']
            del (features_data['FeatureDefinitions'])
        else:
            # Add new categories to existing dictionary
            if not 'Category' in response_dict:
                # No over-ridden categories returned
                continue
            cat_list = response_dict['Category']
            if not isinstance(cat_list, collections.Sequence):
                cat_list = [cat_list]  # in case there is only one category
            # Add the new categories, FeatureDefinitions, ListingDurations
            features_data['Category'].extend(cat_list)
            feature_definitions.update(
                response_dict['FeatureDefinitions'].keys())
            lds = response_dict['FeatureDefinitions']['ListingDurations']
            if 'ListingDuration' in lds:
                for ld in lds['ListingDuration']:
                    if ld['_durationSetID'] in listing_durations:
                        continue
                    listing_durations[ld['_durationSetID']] = ld['Duration']

    # Store the FeatureDefinitions and ListingDurations in a sensible place
    feature_definitions.remove('ListingDurations')
    features_data['FeatureDefinitions'] = feature_definitions
    features_data['ListingDurations'] = listing_durations

    # Move the ConditionHelpURL out of each category and reorganize
    # the Conditions
    for cat in features_data['Category']:
        if 'ConditionValues' in cat:
            cv = cat['ConditionValues']
            if 'ConditionHelpURL' in cv:
                cat['ConditionHelpURL'] = (
                    cv['ConditionHelpURL'])
                del cv['ConditionHelpURL']
            cat['ConditionValues'] = cv['Condition']

    if 'ConditionValues' in features_data['SiteDefaults']:
        cv = features_data['SiteDefaults']['ConditionValues']
        if 'ConditionHelpURL' in cv:
            features_data['SiteDefaults']['ConditionHelpURL'] = (
                cv['ConditionHelpURL'])
            del cv['ConditionHelpURL']
        features_data['SiteDefaults']['ConditionValues'] = cv['Condition']

    # Extract the new version number
    features_version = features_data['CategoryVersion']

    # Return the new features
    return features_version, features_data


@frappe.whitelist()
def GeteBayDetails():
    """Perform a GeteBayDetails call and save the output in geteBayDetails.txt
    in the site root directory
    """
    filename = os.path.join(frappe.utils.get_site_path(),
                            'GeteBayDetails.txt')

    try:
        # Initialize TradingAPI; default timeout is 20.
        api = Trading(domain='api.sandbox.ebay.com', config_file='ebay.yaml',
                      siteid=siteid, warnings=True, timeout=20)

        response = api.execute('GeteBayDetails', {})

    except ConnectionError as e:
        print(e)
        print(e.response.dict())
        raise e

    with open(filename, 'wt') as f:
        f.write(repr(response.dict()))

    return None


def verify_add_item(listing_dict):
    """Perform a VerifyAddItem call, and return useful information"""

    try:
        api = Trading(domain='api.sandbox.ebay.com', config_file='ebay.yaml',
                      siteid=siteid, warnings=True, timeout=20)

        response = api.execute('VerifyAddItem', listing_dict)

    except ConnectionError as e:
        # traverse the DOM to look for error codes
        for node in api.response.dom().findall('ErrorCode'):
            msgprint("error code: %s" % node.text)

        # check for invalid data - error code 37
        if 37 in api.response_codes():
            if 'Errors' in api.response.dict():
                errors_dict = api.response.dict()['Errors']
                errors_list = []
                for key, value in errors_dict.items():
                    errors_list.append('{} : {}'.format(key, value))
                msgprint('\n'.join(errors_list))
                if 'ErrorParameters' in errors_dict:
                    parameter = errors_dict['ErrorParameters']['Value']
                    parameter_stack = parameter.split('.')
                    parameter_value = listing_dict
                    for stack_entry in parameter_stack:
                        parameter_value = parameter_value[stack_entry]
                    msgprint("'{}': '{}'".format(parameter, parameter_value))

        else:
            msgprint("Unknown error: {}".format(api.response_codes()))
            msgprint('{}'.format(e))
            msgprint('{}'.format(e.response.dict()))
        return {'ok': False}

    # Success?
    ok = True
    ret_dict = {'ok': ok}

    msgprint(response.dict())

    return ret_dict
