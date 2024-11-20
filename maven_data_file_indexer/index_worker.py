# pylint: disable=E1101
'''
Created on Mar 17, 2016

@author: bstaley
'''

import os
from collections import namedtuple
import logging
from enum import Enum
from . import utilities


class FILE_EVENT(Enum):
    CLOSED = 1
    REMOVED = 2

    
FileEvent = namedtuple('FileEvent', ['full_filename', 'file_event', 'event_time'])

logger = logging.getLogger('maven.maven_data_file_indexer.index_worker.log')

# Maps the metadata to the insert routine that knows how to insert that metadata
# Key -> Method to build metadata (returns None if the metadata can't be built from the supplied filename
# Value -> The insert method to insert the metadata generated by key
metadata_getters = {utilities.get_metadata_for_science_file: utilities.upsert_science_file_metadatum,
                    utilities.get_metadata_for_ancillary_file: utilities.upsert_ancillary_file_metadatum,
                    utilities.get_metadata_for_metadata_file: utilities.upsert_science_file_metadatum,
                    utilities.get_metadata_for_ql_file: utilities.upsert_science_file_metadatum,
                    utilities.get_metadata_for_l0_file: utilities.upsert_l0_file_metadatum,
                    }


def process_file_updated_event(event):
    for next_metadata_getter in metadata_getters:
        try:
            metadata = next_metadata_getter(event.full_filename)
        except OSError as e:
            metadata = None
            logger.warning('Unable to index file %s due to %s', event.full_filename, e)
        if metadata:
            metadata_getters[next_metadata_getter](metadata)
            logger.debug('Processed metadata using %s', next_metadata_getter)
            break  # Found the correct getter.  No need to check the rest
    else:  # else of a for loop runs when no break happens
        logger.warning('Unable to generate metadata for %s.  No index was built', event)


def process_file_removed_event(event):
    if utilities.is_science_metadata(event.full_filename):
        if not utilities.delete_science_file_metadata_from_filename(os.path.basename(event.full_filename)):
            err_msg = 'Unable to remove science file %s' % event.full_filename
            logger.error(err_msg)
            raise RuntimeError(err_msg)
    # try ancillary
    elif utilities.is_ancillary_metadata(event.full_filename):
        if not utilities.delete_ancillary_file_metadata_from_filename(os.path.basename(event.full_filename)):
            err_msg = 'Unable to remove ancillary file %s' % event.full_filename
            logger.error(err_msg)
            raise RuntimeError(err_msg)
    else:
        logger.warning('Unable to remove index data for file %s.  Unable to determine metadata type', event.full_filename)


def process_file_event(event):
    logger.debug('Index worker handle work request %s', event)

    if event.file_event == FILE_EVENT.CLOSED:
        process_file_updated_event(event)
    elif event.file_event == FILE_EVENT.REMOVED:
        process_file_removed_event(event)
    else:
        logger.warning('Invalid FILE_EVENT type : %s.  No processing will occur', event)


def process_file_events(work_queue, error_queue):
    '''Process logic used to process file system events
    Arguments:
        work_queue - Queue used to receive FileEvents from the parent process
        error_queue - Queue used to send error (exceptions) to parent
    '''

    while True:
        next_event = work_queue.get()
        if next_event is None:
            logger.info('Terminating worker')
            raise Exception('Nominal worker shutdown requested')
        try:
            process_file_event(next_event)
        except Exception as e:
            logger.exception('Stopping file event processing!')
            error_queue.put(e)
            break