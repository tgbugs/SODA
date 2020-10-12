# -*- coding: utf-8 -*-

### Import required python modules
import logging

from gevent import monkey; monkey.patch_all()
import platform
import os
from os import listdir, stat, makedirs, mkdir, walk, remove, pardir
from os.path import isdir, isfile, join, splitext, getmtime, basename, normpath, exists, expanduser, split, dirname, getsize, abspath
import pandas as pd
import time
from time import strftime, localtime
import shutil
from shutil import copy2
from configparser import ConfigParser
import numpy as np
from collections import defaultdict
import subprocess
from websocket import create_connection
import socket
import errno
import re
import gevent
from blackfynn import Blackfynn
from blackfynn.log import get_logger
from blackfynn.api.agent import agent_cmd
from blackfynn.api.agent import AgentError, check_port, socket_address
from urllib.request import urlopen
import json
import collections
from threading import Thread
import pathlib

from datetime import datetime, timezone

from validator_soda import pathToJsonStruct, validate_high_level_folder_structure, validate_high_level_metadata_files, \
validate_sub_level_organization, validate_submission_file, validate_dataset_description_file

from pysoda import clear_queue, agent_running

### Global variables
curateprogress = ' '
curatestatus = ' '
curateprintstatus = ' '
total_dataset_size = 1
curated_dataset_size = 0
start_time = 0

userpath = expanduser("~")
configpath = join(userpath, '.blackfynn', 'config.ini')
submitdataprogress = ' '
submitdatastatus = ' '
submitprintstatus = ' '
total_file_size = 1
uploaded_file_size = 0
start_time_bf_upload = 0
start_submit = 0
metadatapath = join(userpath, 'SODA', 'SODA_metadata')

bf = ""
myds = ""
initial_bfdataset_size = 0
upload_directly_to_bf = 0
initial_bfdataset_size_submit = 0

forbidden_characters = '<>:"/\|?*'
forbidden_characters_bf = '\/:*?"<>'

DEV_TEMPLATE_PATH = join(dirname(__file__), "..", "file_templates")

# once pysoda has been packaged with pyinstaller
# it becomes nested into the pysodadist/api directory
PROD_TEMPLATE_PATH = join(dirname(__file__), "..", "..", "file_templates")
TEMPLATE_PATH = DEV_TEMPLATE_PATH if exists(DEV_TEMPLATE_PATH) else PROD_TEMPLATE_PATH

logging.basicConfig(level=logging.DEBUG, filename=os.path.join(os.path.expanduser("~"), f"{__name__}.log"))
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(os.path.join(os.path.expanduser("~"), f"{__name__}.log"))
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)


### Internal functions
def TZLOCAL():
    return datetime.now(timezone.utc).astimezone().tzinfo

def open_file(file_path):
    """
    Opening folder on all platforms
    https://stackoverflow.com/questions/6631299/python-opening-a-folder-in-explorer-nautilus-mac-thingie

    Args:
        file_path: path of the folder (string)
    Action:
        Opens file explorer window to the given path
    """
    try:
        if platform.system() == "Windows":
            subprocess.Popen(r'explorer /select,' + str(file_path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", file_path])
        else:
            subprocess.Popen(["xdg-open", file_path])
    except Exception as e:
        raise e


def folder_size(path):
    """
    Provides the size of the folder indicated by path

    Args:
        path: path of the folder (string)
    Returns:
        total_size: total size of the folder in bytes (integer)
    """
    total_size = 0
    start_path = '.'  # To get size of current directory
    for path, dirs, files in walk(path):
        for f in files:
            fp = join(path, f)
            total_size += getsize(fp)
    return total_size


def bf_dataset_size():
    """
    Function to get storage size of a dataset on Blackfynn
    """
    global bf
    global myds

    try:
        selected_dataset_id = myds.id
        bf_response = bf._api._get('/datasets/' + str(selected_dataset_id))
        return bf_response['storage'] if 'storage' in bf_response.keys() else 0
    except Exception as e:
        raise e

def path_size(path):
    """
    Returns size of the path, after checking if it's a folder or a file
    Args:
        path: path of the file/folder (string)
    Returns:
        total_size: total size of the file/folder in bytes (integer)
    """
    if isdir(path):
        return folder_size(path)
    else:
        return getsize(path)


def create_folder_level_manifest(jsonpath, jsondescription):
    """
    Function to create manifest files for each SPARC folder.
    Files are created in a temporary folder

    Args:
        datasetpath: path of the dataset (string)
        jsonpath: all paths in json format with key being SPARC folder names (dictionary)
        jsondescription: description associated with each path (dictionary)
    Action:
        Creates manifest files in xslx format for each SPARC folder
    """
    global total_dataset_size
    local_timezone = TZLOCAL()

    try:
        datasetpath = metadatapath
        shutil.rmtree(datasetpath) if isdir(datasetpath) else 0
        makedirs(datasetpath)
        folders = list(jsonpath.keys())
        if 'main' in folders:
            folders.remove('main')
        # In each SPARC folder, generate a manifest file
        for folder in folders:
            if (jsonpath[folder] != []):
                # Initialize dataframe where manifest info will be stored
                df = pd.DataFrame(columns=['filename', 'timestamp', 'description',
                                        'file type', 'Additional Metadata'])
                # Get list of files/folders in the the folder
                # Remove manifest file from the list if already exists
                folderpath = join(datasetpath, folder)
                allfiles = jsonpath[folder]
                alldescription = jsondescription[folder + '_description']
                manifestexists = join(folderpath, 'manifest.xlsx')

                countpath = -1
                for pathname in allfiles:
                    countpath += 1
                    if basename(pathname) == 'manifest.csv' or basename(pathname) == 'manifest.xlsx':
                        allfiles.pop(countpath)
                        alldescription.pop(countpath)

                # Populate manifest dataframe
                filename, timestamp, filetype, filedescription = [], [], [], []
                countpath = -1
                for paths in allfiles:
                    if isdir(paths):
                        key = basename(paths)
                        alldescription.pop(0)
                        for subdir, dirs, files in os.walk(paths):
                            for file in files:
                                gevent.sleep(0)
                                filepath = pathlib.Path(paths) / subdir / file
                                mtime = filepath.stat().st_mtime
                                lastmodtime = datetime.fromtimestamp(mtime).astimezone(local_timezone)
                                timestamp.append(lastmodtime.isoformat().replace('.', ',').replace('+00:00', 'Z'))
                                fullfilename = filepath.name

                                if folder == 'main': # if file in main folder
                                    filename.append(fullfilename) if folder == '' else filename.append(join(folder, fullfilename))
                                else:
                                    subdirname = os.path.relpath(subdir, paths) # gives relative path of the directory of the file w.r.t paths
                                    if subdirname == '.':
                                        filename.append(join(key, fullfilename))
                                    else:
                                        filename.append(join(key, subdirname, fullfilename))

                                fileextension = splitext(fullfilename)[1]
                                if not fileextension:  # if empty (happens e.g. with Readme files)
                                    fileextension = 'None'
                                filetype.append(fileextension)
                                filedescription.append('')
                    else:
                        gevent.sleep(0)
                        countpath += 1
                        filepath = pathlib.Path(paths)
                        file = filepath.name
                        filename.append(file)
                        mtime = filepath.stat().st_mtime
                        lastmodtime = datetime.fromtimestamp(mtime).astimezone(local_timezone)
                        timestamp.append(lastmodtime.isoformat().replace('.', ',').replace('+00:00', 'Z'))
                        filedescription.append(alldescription[countpath])
                        if isdir(paths):
                            filetype.append('folder')
                        else:
                            fileextension = splitext(file)[1]
                            if not fileextension:  #if empty (happens e.g. with Readme files)
                                fileextension = 'None'
                            filetype.append(fileextension)

                df['filename'] = filename
                df['timestamp'] = timestamp
                df['file type'] = filetype
                df['description'] = filedescription

                makedirs(folderpath)
                # Save manifest as Excel sheet
                manifestfile = join(folderpath, 'manifest.xlsx')
                df.to_excel(manifestfile, index=None, header=True)
                total_dataset_size += path_size(manifestfile)
                jsonpath[folder].append(manifestfile)

        return jsonpath

    except Exception as e:
        raise e


def check_forbidden_characters(my_string):
    """
    Check for forbidden characters in file/folder name

    Args:
        my_string: string with characters (string)
    Returns:
        False: no forbidden character
        True: presence of forbidden character(s)
    """
    regex = re.compile('[' + forbidden_characters + ']')
    if(regex.search(my_string) == None and "\\" not in r"%r" % my_string):
        return False
    else:
        return True

def check_forbidden_characters_bf(my_string):
    """
    Check for forbidden characters in blackfynn file/folder name

    Args:
        my_string: string with characters (string)
    Returns:
        False: no forbidden character
        True: presence of forbidden character(s)
    """
    regex = re.compile('[' + forbidden_characters_bf + ']')
    if(regex.search(my_string) == None and "\\" not in r"%r" % my_string):
        return False
    else:
        return True

def return_new_path(topath):
    """
    This function checks if a folder already exists and in such cases,
    appends (2) or (3) etc. to the folder name

    Args:
        topath: path where the folder is supposed to be created (string)
    Returns:
        topath: new folder name based on the availability in destination folder (string)
    """
    if exists(topath):
        i = 2
        while True:
            if not exists(topath + ' (' + str(i) + ')'):
                return topath + ' (' + str(i) + ')'
            i += 1
    else:
        return topath

def time_format(elapsed_time):
    mins, secs = divmod(elapsed_time, 60)
    hours, mins = divmod(mins, 60)
    return "%dh:%02dmin:%02ds" % (hours, mins, secs)

def mycopyfileobj(fsrc, fdst, length=16*1024*16):
    """
    Helper function to copy file

    Args:
        fsrc: source file opened in python (file-like object)
        fdst: destination file accessed in python (file-like object)
        length: copied buffer size in bytes (integer)
    """
    global curateprogress
    global total_dataset_size
    global curated_dataset_size
    while True:
        buf = fsrc.read(length)
        if not buf:
            break
        gevent.sleep(0)
        fdst.write(buf)
        curated_dataset_size += len(buf)

def mycopyfile_with_metadata(src, dst, *, follow_symlinks=True):
    """
    Copy file src to dst with metadata (timestamp, permission, etc.) conserved

    Args:
        src: source file (string)
        dst: destination file (string)
    Returns:
        dst
    """
    if not follow_symlinks and os.path.islink(src):
        os.symlink(os.readlink(src), dst)
    else:
        with open(src, 'rb') as fsrc:
            with open(dst, 'wb') as fdst:
                mycopyfileobj(fsrc, fdst)
    shutil.copystat(src, dst)
    return dst


### Prepare dataset
def save_file_organization(jsonpath, jsondescription, jsonpathmetadata, pathsavefileorganization):
    """
    Associated with 'Save' button in the SODA interface
    Saves the paths and associated descriptions from the interface table to a CSV file for future use
    Each json key (SPARC foler name) becomes a header in the CSV

    Args:
        jsonpath: paths of all files (dictionary)
        jsondescription: description associated with each file (dictionary)
        pathsavefileorganization: destination path for CSV file to be saved (string)
    Action:
        Creates CSV file with path and description for files in SPARC folders
    """
    try:
        mydict = jsonpath
        mydict2 = jsondescription
        mydict3 = jsonpathmetadata
        mydict.update(mydict2)
        mydict.update(mydict3)
        dictkeys = list(mydict.keys())
        dictkeys.sort()
        df = pd.DataFrame(columns=[dictkeys[0]])
        df[dictkeys[0]] = mydict[dictkeys[0]]
        for i in range(1,len(dictkeys)):
            dfnew = pd.DataFrame(columns=[dictkeys[i]])
            dfnew[dictkeys[i]] = mydict[dictkeys[i]]
            df = pd.concat([df, dfnew], axis=1)
        df = df.replace(np.nan, '', regex=True)
        csvsavepath = join(pathsavefileorganization)
        df.to_csv(csvsavepath, index = None, header=True)
        return 'Saved!'
    except Exception as e:
        raise e


def import_file_organization(pathuploadfileorganization, headernames):
    """
    Associated with 'Import' button in the SODA interface
    Import previously saved progress (CSV file) for viewing in the SODA interface

    Args:
        pathuploadfileorganization: path of previously saved CSV file (string)
        headernames: names of SPARC folder (list of strings)
    Returns:
        mydict: dictionary with headers of CSV file as keys and cell contents as list of strings for each key
    """
    try:
        csvsavepath = join(pathuploadfileorganization)
        df = pd.read_csv(csvsavepath)
        dfnan = df.isnull()
        mydict = {}
        mydictmetadata ={}
        dictkeys = df.columns
        compare = lambda x, y: collections.Counter(x) == collections.Counter(y)
        if not compare(dictkeys, headernames):
            raise Exception("Error: Please select a valid file")
        rowcount = len(df.index)
        for i in range(len(dictkeys)):
            pathvect = []
            for j in range(rowcount):
                pathval = df.at[j, dictkeys[i]]
                if not dfnan.at[j, dictkeys[i]]:
                    pathvect.append(pathval)
                else:
                    pathvect.append("")
            if dictkeys[i] == 'metadata':
                mydictmetadata[dictkeys[i]] = pathvect
            else:
                mydict[dictkeys[i]] = pathvect
        return [mydict, mydictmetadata]
    except Exception as e:
        raise e


def create_preview_files(paths, folder_path):
    """
    Creates folders and empty files from original 'paths' to the destination 'folder_path'

    Args:
        paths: paths of all the files that need to be copied (list of strings)
        folder_path: Destination to which the files / folders need to be copied (string)
    Action:
        Creates folders and empty files at the given 'folder_path'
    """
    try:
        for p in paths:
            gevent.sleep(0)
            if isfile(p):
                file = basename(p)
                open(join(folder_path, file), 'a').close()
            else:
                all_files = listdir(p)
                all_files_path = []
                for f in all_files:
                    all_files_path.append(join(p, f))

                pname = basename(p)
                new_folder_path = join(folder_path, pname)
                makedirs(new_folder_path)
                create_preview_files(all_files_path, new_folder_path)
        return
    except Exception as e:
        raise e


def preview_file_organization(jsonpath):
    """
    Associated with 'Preview' button in the SODA interface
    Creates a folder for preview and adds mock files from SODA table (same name as origin but 0 kb in size)
    Opens the dialog box to showcase the files / folders added

    Args:
        jsonpath: dictionary containing all paths (keys are SPARC folder names)
    Action:
        Opens the dialog box at preview_path
    Returns:
        preview_path: path of the folder where the preview files are located
    """
    mydict = jsonpath
    preview_path = join(userpath, "SODA", "Preview")
    try:
        if isdir(preview_path):
            delete_preview_file_organization()
            makedirs(preview_path)
        else:
            makedirs(preview_path)
    except Exception as e:
        raise e

    try:

        folderrequired = []
        for i in mydict.keys():
            if mydict[i] != []:
                folderrequired.append(i)
                if i != 'main':
                    makedirs(join(preview_path, i))

        def preview_func(folderrequired, preview_path):
            for i in folderrequired:
                paths = mydict[i]
                if (i == 'main'):
                    create_preview_files(paths, join(preview_path))
                else:
                    create_preview_files(paths, join(preview_path, i))
        output = []
        output.append(gevent.spawn(preview_func, folderrequired, preview_path))
        gevent.sleep(0)
        gevent.joinall(output)

        if len(listdir(preview_path)) > 0:
            folder_in_preview = listdir(preview_path)[0]

            open_file(join(preview_path, folder_in_preview))

        else:
            open_file(preview_path)

        return preview_path

    except Exception as e:
        raise e


def delete_preview_file_organization():
    """
    Associated with 'Delete Preview Folder' button of the SODA interface

    Action:
        Deletes the 'Preview' folder from the disk
    """
    try:
        userpath = expanduser("~")
        preview_path = join(userpath, "SODA", "Preview")
        if isdir(preview_path):
            shutil.rmtree(preview_path, ignore_errors=True)
        else:
            raise Exception("Error: Preview folder not present or already deleted!")
    except Exception as e:
        raise e


def create_dataset(jsonpath, pathdataset):
    """
    Associated with 'Create new dataset locally' option of SODA interface
    for creating requested folders and files to the destination path specified

    Args:
        jsonpath: all paths (dictionary, keys are SPARC folder names)
        pathdataset: destination path for creating a new dataset as specified (string)
    Action:
        Creates the folders and files specified
    """
    global curateprogress

    try:
        mydict = jsonpath
        folderrequired = []

        #create SPARC folder structure
        for i in mydict.keys():
            if mydict[i] != []:
                folderrequired.append(i)
                if i != 'main':
                    makedirs(join(pathdataset, i))

        # create all subfolders and generate a list of all files to copy
        listallfiles = []
        for i in folderrequired:
            if i == 'main':
                outputpath = pathdataset
            else:
                outputpath = join(pathdataset, i)
            for tablepath in mydict[i]:
                if isdir(tablepath):
                    foldername = basename(tablepath)
                    outputpathdir = join(outputpath, foldername)
                    if not os.path.isdir(outputpathdir):
                        os.mkdir(outputpathdir)
                    for dirpath, dirnames, filenames in os.walk(tablepath):
                        distdir = os.path.join(outputpathdir, os.path.relpath(dirpath, tablepath))
                        if not os.path.isdir(distdir):
                            os.mkdir(distdir)
                        for file in filenames:
                            srcfile = os.path.join(dirpath, file)
                            distfile = os.path.join(distdir, file)
                            listallfiles.append([srcfile, distfile])
                else:
                    srcfile = tablepath
                    file = basename(tablepath)
                    distfile= os.path.join(outputpath, file)
                    listallfiles.append([srcfile, distfile])

        # copy all files to corresponding folders
        for fileinfo in listallfiles:
            srcfile = fileinfo[0]
            distfile = fileinfo[1]
            curateprogress = 'Copying ' + str(srcfile)
            mycopyfile_with_metadata(srcfile, distfile)

    except Exception as e:
        raise e

def bf_get_current_user_permission(bf, myds):

    """
    Function to get the permission of currently logged in user for a selected dataset

    Args:
        bf: logged Blackfynn acccount (dict)
        myds: selected Blackfynn dataset (dict)
    Output:
        permission of current user (string)
    """

    try:
        selected_dataset_id = myds.id
        user_role = bf._api._get('/datasets/' + str(selected_dataset_id) + '/role')['role']

        return user_role

    except Exception as e:
        raise e


def curate_dataset(sourcedataset, destinationdataset, pathdataset, newdatasetname,\
        manifeststatus, jsonpath, jsondescription):
    """
    Associated with 'Generate' button in the 'Generate dataset' section of SODA interface
    Checks validity of files / paths / folders and then generates the files and folders
    as requested along with progress status

    Args:
        sourcedataset: state of the source dataset ('already organized' or 'not organized')
        destinationdataset: type of destination dataset ('modify existing', 'create new', or 'upload to blackfynn')
        pathdataset: destination path of new dataset if created locally or name of blackfynn account (string)
        newdatasetname: name of the local dataset or name of the dataset on blackfynn (string)
        manifeststatus: boolean to check if user request manifest files
        jsonpath: path of the files to be included in the dataset (dictionary)
        jsondescription: associated description to be included in manifest file (dictionary)
    """
    global curatestatus #set to 'Done' when completed or error to stop progress tracking from front-end
    global curateprogress #GUI messages shown to user to provide update on progress
    global curateprintstatus # If = "Curating" Progress messages are shown to user
    global total_dataset_size # total size of the dataset to be generated
    global curated_dataset_size # total size of the dataset generated (locally or on blackfynn) at a given time
    global start_time
    global bf
    global myds
    global upload_directly_to_bf
    global start_submit
    global initial_bfdataset_size

    curateprogress = ' '
    curatestatus = ''
    curateprintstatus = ' '
    error, c = '', 0
    curated_dataset_size = 0
    start_time = 0
    upload_directly_to_bf = 0
    start_submit = 0
    initial_bfdataset_size = 0

    # if sourcedataset == 'already organized':
    #     if not isdir(pathdataset):
    #         curatestatus = 'Done'
    #         raise Exception('Error: Please select a valid dataset folder')

    if destinationdataset == 'create new':
        if not isdir(pathdataset):
            curatestatus = 'Done'
            raise Exception('Error: Please select a valid folder for new dataset')
        if not newdatasetname:
            curatestatus = 'Done'
            raise Exception('Error: Please enter a valid name for new dataset folder')
        if check_forbidden_characters(newdatasetname):
            curatestatus = 'Done'
            raise Exception('Error: A folder name cannot contain any of the following characters ' + forbidden_characters)

    # check if path in jsonpath are valid and calculate total dataset size
    error, c = '', 0
    total_dataset_size = 1
    for folders in jsonpath.keys():
        if jsonpath[folders] != []:
            for path in jsonpath[folders]:
                if exists(path):

                    if isfile(path):
                        mypathsize =  getsize(path)
                        if mypathsize == 0:
                            c += 1
                            error = error + path + ' is 0 KB <br>'
                        else:
                            total_dataset_size += mypathsize
                    else:

                        myfoldersize = folder_size(path)
                        if myfoldersize == 0:
                            c += 1
                            error = error + path + ' is empty <br>'
                        else:
                            for path, dirs, files in walk(path):
                                for f in files:
                                    fp = join(path, f)
                                    mypathsize =  getsize(fp)
                                    if mypathsize == 0:
                                        c += 1
                                        error = error + fp + ' is 0 KB <br>'
                                    else:
                                        total_dataset_size += mypathsize
                                for d in dirs:
                                    dp = join(path,d)
                                    myfoldersize = folder_size(dp)
                                    if myfoldersize == 0:
                                        c += 1
                                        error = error + dp + ' is empty <br>'
                else:
                    c += 1
                    error = error + path + ' does not exist <br>'

    if c > 0:
        error = error + '<br>Please remove invalid files/folders from your dataset and try again'
        curatestatus = 'Done'
        raise Exception(error)

    total_dataset_size = total_dataset_size - 1

    # Add metadata to jsonpath
    curateprogress = 'Generating metadata'

    if manifeststatus:
        try:
            jsonpath = create_folder_level_manifest(jsonpath, jsondescription)
        except Exception as e:
            curatestatus = 'Done'
            raise e

    # CREATE NEW
    if destinationdataset == 'create new':
        try:
            pathnewdatasetfolder = join(pathdataset, newdatasetname)
            pathnewdatasetfolder  = return_new_path(pathnewdatasetfolder)
            open_file(pathnewdatasetfolder)

            curateprogress = 'Started'
            curateprintstatus = 'Curating'
            start_time = time.time()
            start_submit = 1

            pathdataset = pathnewdatasetfolder
            mkdir(pathdataset)
            create_dataset(jsonpath, pathdataset)

            curateprogress = 'New dataset created'
            curateprogress = 'Success: COMPLETED!'
            curatestatus = 'Done'
            shutil.rmtree(metadatapath) if isdir(metadatapath) else 0

        except Exception as e:
            curatestatus = 'Done'
            shutil.rmtree(metadatapath) if isdir(metadatapath) else 0
            raise e

    # UPLOAD TO BLACKFYNN
    elif destinationdataset == 'upload to blackfynn':
        error, c = '', 0
        accountname = pathdataset
        bfdataset = newdatasetname
        upload_directly_to_bf = 1

        try:
            bf = Blackfynn(accountname)
        except Exception as e:
            curatestatus = 'Done'
            error = error + 'Error: Please select a valid Blackfynn account<br>'
            c += 1

        try:
            myds = bf.get_dataset(bfdataset)
        except Exception as e:
            curatestatus = 'Done'
            error = error + 'Error: Please select a valid Blackfynn dataset<br>'
            c += 1

        if c>0:
            shutil.rmtree(metadatapath) if isdir(metadatapath) else 0
            raise Exception(error)

        try:
            role = bf_get_current_user_permission(bf, myds)
            if role not in ['owner', 'manager', 'editor']:
                curatestatus = 'Done'
                error = "Error: You don't have permissions for uploading to this Blackfynn dataset"
                raise Exception(error)
        except Exception as e:
            raise e

        clear_queue()
        try:
            agent_running()
            def calluploaddirectly():

                try:
                    global curateprogress
                    global curatestatus

                    myds = bf.get_dataset(bfdataset)

                    for folder in jsonpath.keys():
                        if jsonpath[folder] != []:
                            if folder != 'main':
                                mybffolder = myds.create_collection(folder)
                            else:
                                mybffolder = myds
                            for mypath in jsonpath[folder]:
                                if isdir(mypath):
                                    curateprogress = "Uploading folder '%s' to dataset '%s' " %(mypath, bfdataset)
                                    mybffolder.upload(mypath, recursive=True, use_agent=True)
                                else:
                                    curateprogress = "Uploading file '%s' to dataset '%s' " %(mypath, bfdataset)
                                    mybffolder.upload(mypath, use_agent=True)

                    curateprogress = 'Success: COMPLETED!'
                    curatestatus = 'Done'
                    shutil.rmtree(metadatapath) if isdir(metadatapath) else 0

                except Exception as e:
                    shutil.rmtree(metadatapath) if isdir(metadatapath) else 0
                    raise e


            curateprintstatus = 'Curating'
            start_time = time.time()
            initial_bfdataset_size = bf_dataset_size()
            start_submit = 1
            gev = []
            gev.append(gevent.spawn(calluploaddirectly))
            gevent.sleep(0)
            gevent.joinall(gev) #wait for gevent to finish before exiting the function
            curatestatus = 'Done'

            try:
                return gev[0].get()
            except Exception as e:
                raise e

        except Exception as e:
            curatestatus = 'Done'
            shutil.rmtree(metadatapath) if isdir(metadatapath) else 0
            raise e

def curate_dataset_progress():
    """
    Function frequently called by front end to help keep track of the dataset generation progress
    """
    global curateprogress
    global curatestatus
    global curateprintstatus
    global total_dataset_size
    global curated_dataset_size
    global start_time
    global upload_directly_to_bf
    global start_submit
    global initial_bfdataset_size

    if start_submit == 1:
        if upload_directly_to_bf == 1:
            curated_dataset_size = bf_dataset_size() - initial_bfdataset_size
        elapsed_time = time.time() - start_time
        elapsed_time_formatted = time_format(elapsed_time)
        elapsed_time_formatted_display = '<br>' + 'Elapsed time: ' + elapsed_time_formatted + '<br>'
    else:
        if upload_directly_to_bf == 1:
            curated_dataset_size = 0
        elapsed_time_formatted = 0
        elapsed_time_formatted_display = '<br>' + 'Initiating...' + '<br>'

    return (curateprogress+elapsed_time_formatted_display, curatestatus, curateprintstatus, total_dataset_size, curated_dataset_size, elapsed_time_formatted)

### Validate dataset
def validate_dataset(validator_input):
    try:
        if type(validator_input) is str:
            jsonStruct = pathToJsonStruct(validator_input)
        elif type(validator_input) is dict:
            jsonStruct = validator_input
        else:
            raise Exception('Error: validator input must be string (path to dataset) or a SODA JSON Structure/Python dictionary')

        res = []

        validatorHighLevelFolder = validate_high_level_folder_structure(jsonStruct)
        validatorObj = validatorHighLevelFolder
        resitem = {}
        resitem['pass'] = validatorObj.passes
        resitem['warnings'] = validatorObj.warnings
        resitem['fatal'] = validatorObj.fatal
        res.append(resitem)

        validatorHighLevelMetadataFiles, isSubmission, isDatasetDescription, isSubjects, isSamples = \
         validate_high_level_metadata_files(jsonStruct)
        validatorObj = validatorHighLevelMetadataFiles
        resitem = {}
        resitem['pass'] = validatorObj.passes
        resitem['warnings'] = validatorObj.warnings
        resitem['fatal'] = validatorObj.fatal
        res.append(resitem)

        validatorSubLevelOrganization = validate_sub_level_organization(jsonStruct)
        validatorObj = validatorSubLevelOrganization
        resitem = {}
        resitem['pass'] = validatorObj.passes
        resitem['warnings'] = validatorObj.warnings
        resitem['fatal'] = validatorObj.fatal
        res.append(resitem)

        if isSubmission == 1:
            metadataFiles = jsonStruct['main']
            for f in metadataFiles:
                fullName = os.path.basename(f)
                if os.path.splitext(fullName)[0] == 'submission':
                    subFilePath = f
            validatorSubmissionFile = validate_submission_file(subFilePath)
            validatorObj = validatorSubmissionFile
            resitem = {}
            resitem['pass'] = validatorObj.passes
            resitem['warnings'] = validatorObj.warnings
            resitem['fatal'] = validatorObj.fatal
            res.append(resitem)
        elif isSubmission == 0:
            resitem = {}
            resitem['warnings'] = ["Include a 'submission' file in a valid format to check it through the validator"]
            res.append(resitem)

        elif isSubmission>1:
            resitem = {}
            resitem['warnings'] = ["Include a unique 'submission' file to check it through the validator"]
            res.append(resitem)

        if isDatasetDescription == 1:
            metadataFiles = jsonStruct['main']
            for f in metadataFiles:
                fullName = os.path.basename(f)
                if os.path.splitext(fullName)[0] == 'dataset_description':
                    ddFilePath = f
            validatorDatasetDescriptionFile = validate_dataset_description_file(ddFilePath)
            validatorObj = validatorDatasetDescriptionFile
            resitem = {}
            resitem['pass'] = validatorObj.passes
            resitem['warnings'] = validatorObj.warnings
            resitem['fatal'] = validatorObj.fatal
            res.append(resitem)

        elif isDatasetDescription == 0:
            resitem = {}
            resitem['warnings'] = ["Include a 'dataset_description' file in a valid format to check it through the validator"]
            res.append(resitem)
        elif isDatasetDescription>1:
            resitem = {}
            resitem['warnings'] = ["Include a unique 'dataset_description' file to check it through the validator"]
            res.append(resitem)

        return res

    except Exception as e:
        raise e