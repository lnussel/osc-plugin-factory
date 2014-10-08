#!/usr/bin/python
# Copyright (c) 2014 SUSE Linux Products GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from pprint import pprint
import os, sys, re
import logging
from optparse import OptionParser

try:
    from xml.etree import cElementTree as ET
except ImportError:
    import cElementTree as ET

import osc.conf
import osc.core
import urllib2

parser = OptionParser()
parser.add_option("--factory", metavar="project", help="the openSUSE Factory project")
parser.add_option("--apiurl", '-A', metavar="URL", help="api url")
parser.add_option("--dry", action="store_true", help="dry run")
parser.add_option("--debug", action="store_true", help="debug output")
parser.add_option("--verbose", action="store_true", help="verbose")

(options, args) = parser.parse_args()

logging.basicConfig()
logger = logging.getLogger("factorychecker")
if (options.debug):
    logger.setLevel(logging.DEBUG)
elif (options.verbose):
    logger.setLevel(logging.INFO)

class Checker(object):
    requests = []

    def __init__(self, apiurl = None, factory = None, dryrun = False):
        self.apiurl = apiurl
        self.factory = factory
        self.dryrun = dryrun

        if self.factory is None:
            self.factory = "openSUSE:Factory"

    def set_request_ids(self, ids):
        for rqid in ids:
            u = osc.core.makeurl(self.apiurl, [ 'request', rqid ])
            r = osc.core.http_GET(u)
            root = ET.parse(r).getroot()
            req = osc.core.Request()
            req.read(root)
            self.requests.append(req)

    def check_requests(self):
        for req in self.requests:
            self._check_one_request(req)

    def _check_one_request(self, req):
        for a in req.actions:
            if a.type == 'maintenance_incident':
                self._check_package(a.src_project, a.src_package, a.src_rev, a.tgt_releaseproject, a.src_package)
            elif a.type == 'submit':
                rev = self._get_verifymd5(a.src_project, a.src_package, a.src_rev)
                self._check_package(a.src_project, a.src_package, rev, a.tgt_package, a.tgt_package)
            else:
                print >> sys.stderr, "unhandled request type %s"%a.type

    def _check_package(self, src_project, src_package, src_rev, target_project, target_package):
        logger.info("%s/%s@%s -> %s/%s"%(src_project, src_package, src_rev, target_project, target_package))
        good = self._check_factory(src_rev, target_package)

        if not good:
            good = self._check_requests(src_rev, target_package)

        if good is None:
            logger.debug("ignoring")
        elif good:
            logger.debug("accepting")
        else:
            logger.debug("declining")
    
    def _check_factory(self, rev, package):
        logger.debug("checking %s in %s"%(package, self.factory))
        u = osc.core.makeurl(self.apiurl, [ 'source', self.factory, package ])
        r = None
        try:
            r = osc.core.http_GET(u)
        except urllib2.HTTPError, e:
            logger.debug("not found")
            return None

        root = ET.parse(r).getroot()
        srcmd5 = root.get('srcmd5')
        if rev == srcmd5:
            logger.debug("srcmd5 matches")
            return True

        logger.debug("srcmd5 not the latest version, checking history")
        u = osc.core.makeurl(self.apiurl, [ 'source', self.factory, package, '_history' ], { 'limit': '5' })
        try:
            r = osc.core.http_GET(u)
        except urllib2.HTTPError, e:
            logger.debug("package has no history!?")
            return None

        root = ET.parse(r).getroot()
        for revision in root.findall('revision'):
            node = revision.find('srcmd5')
            if node and node.text == rev:
                logger.debug("got it, rev %s"%revision.get('rev'))
                return True

        logger.debug("srcmd5 not found in history either")
        return False

    def _check_requests(self, rev, package):
#        xpath = 'submit/target/@project=\'%(project)s\'' \
#            + 'submit/target/@package=\'%(package)s\'' \
#            + 'and state/@name=\'new\'' \
#            %{'project':self.factory, 'package': package}
#        res = search(apiurl, request=xpath)
#        collection = res['request']
#            for root in collection.findall('request'):
#        r = Request()
#        r.read(root)
        logger.debug("checking requests")
        requests = osc.core.get_request_list(self.apiurl, self.factory, package, None, ['new'], 'submit')
        for req in requests:
            for a in req.actions:
                rqrev = self._get_verifymd5(a.src_project, a.src_package, a.src_rev)
                logger.debug("rq %s: %s/%s@%s"%(req.reqid, a.src_project, a.src_package, rqrev))
                if rqrev == rev:
                    logger.debug("srcmd5 matches")
                    return True
        return False

    def _get_verifymd5(self, src_project, src_package, rev=None):
        query = { 'view': 'info' }
        if rev:
            query['rev'] = rev
        url = osc.core.makeurl(self.apiurl, ('source', src_project, src_package), query=query)
        try:
            root = ET.parse(osc.core.http_GET(url)).getroot()
        except urllib2.HTTPError:
            return None

        if root is not None:
            srcmd5 = root.get('verifymd5')
            return srcmd5

osc.conf.get_config(override_apiurl = options.apiurl)

#if (options.debug):
#    osc.conf.config['debug'] = 1

checker = Checker(apiurl = osc.conf.config['apiurl'], factory = options.factory, dryrun = options.dry)
checker.set_request_ids(args)
checker.check_requests()

# vim: sw=4 et