# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------------
# Name:         sfp_dnsraw
# Purpose:      SpiderFoot plug-in for collecting raw DNS records.
#               Also extracts hostnames from SPF records.
#
# Author:      Steve Micallef <steve@binarypool.com>
#
# Created:     07/07/2017
# Copyright:   (c) Steve Micallef 2017
# Licence:     GPL
# -------------------------------------------------------------------------------

import re

import dns.resolver
import dns.query
import dns.rdatatype
from sflib import SpiderFoot, SpiderFootPlugin, SpiderFootEvent

class sfp_dnsraw(SpiderFootPlugin):
    """DNS Raw Records:Footprint,Investigate,Passive:DNS::Retrieves raw DNS records such as MX, TXT and others."""

    # Default options
    opts = {
        'verify': True,
    }

    # Option descriptions
    optdescs = {
        'verify': "Verify identified hostnames resolve."
    }

    events = None
    checked = None

    def setup(self, sfc, userOpts=dict()):
        self.sf = sfc
        self.events = self.tempStorage()
        self.checked = self.tempStorage()
        self.__dataSource__ = "DNS"

        for opt in list(userOpts.keys()):
            self.opts[opt] = userOpts[opt]

    # What events is this module interested in for input
    def watchedEvents(self):
        return ['INTERNET_NAME', 'DOMAIN_NAME', 'DOMAIN_NAME_PARENT']

    # What events this module produces
    # This is to support the end user in selecting modules based on events
    # produced.
    def producedEvents(self):
        return ["PROVIDER_MAIL", "PROVIDER_DNS", "RAW_DNS_RECORDS", "DNS_TEXT", "DNS_SPF",
                'INTERNET_NAME', 'INTERNET_NAME_UNRESOLVED',
                'AFFILIATE_INTERNET_NAME', 'AFFILIATE_INTERNET_NAME_UNRESOLVED']

    # Handle events sent to this module
    def handleEvent(self, event):
        eventName = event.eventType
        srcModuleName = event.module
        eventData = event.data
        eventDataHash = self.sf.hashstring(eventData)
        parentEvent = event

        self.sf.debug("Received event, %s, from %s" % (eventName, srcModuleName))

        if eventDataHash in self.events:
            self.sf.debug("Skipping duplicate event for " + eventData)
            return None

        self.events[eventDataHash] = True

        self.sf.debug("Gathering DNS records for " + eventData)

        domains = list()

        # Process the raw data alone
        recs = {
            'CNAME': r'\S+\s+(?:\d+)?\s+IN\s+CNAME\s+(\S+)\.',
            'MX': r'\S+\s+(?:\d+)?\s+IN\s+MX\s+\d+\s+(\S+)\.',
            'NS': r'\S+\s+(?:\d+)?\s+IN\s+NS\s+(\S+)\.',
            'TXT': r'\S+\s+TXT\s+\"(.[^\"]*)"'
        }

        for rec in list(recs.keys()):
            if self.checkForStop():
                return None

            try:
                req = dns.message.make_query(eventData, dns.rdatatype.from_text(rec))

                if self.opts.get('_dnsserver', "") != "":
                    n = self.opts['_dnsserver']
                else:
                    ns = dns.resolver.get_default_resolver()
                    n = ns.nameservers[0]

                res = dns.query.udp(req, n, timeout=30)

                if not len(res.answer):
                    continue
            except BaseException as e:
                self.sf.error("Failed to obtain DNS response for %s (%s)" % (eventData, e), False)
                continue

            # Iterate through DNS answers
            for x in res.answer:
                if str(x) in self.checked:
                    continue

                self.checked[str(x)] = True

                evt = SpiderFootEvent("RAW_DNS_RECORDS", str(x), self.__name__, parentEvent)
                self.notifyListeners(evt)

                for rx in list(recs.keys()):
                    self.sf.debug("Checking " + str(x) + " + against " + recs[rx])
                    pat = re.compile(recs[rx], re.IGNORECASE | re.DOTALL)
                    grps = re.findall(pat, str(x))

                    if len(grps) == 0:
                        continue

                    for m in grps:
                        self.sf.debug("Matched: " + m)
                        strdata = str(m)

                        if rx == "CNAME":
                            domains.append(strdata.lower())

                        if rx == "MX":
                            evt = SpiderFootEvent("PROVIDER_MAIL", strdata.lower(), self.__name__, parentEvent)
                            self.notifyListeners(evt)
                            domains.append(strdata.lower())

                        if rx == "NS":
                            evt = SpiderFootEvent("PROVIDER_DNS", strdata.lower(), self.__name__, parentEvent)
                            self.notifyListeners(evt)
                            domains.append(strdata.lower())

                        if rx == "TXT":
                            evt = SpiderFootEvent("DNS_TEXT", strdata, self.__name__, parentEvent)
                            self.notifyListeners(evt)

                            if "v=spf" in strdata or "spf2.0/" in strdata:
                                evt = SpiderFootEvent("DNS_SPF", strdata, self.__name__, parentEvent)
                                self.notifyListeners(evt)

                                matches = re.findall(r'include:(.+?) ', strdata, re.IGNORECASE | re.DOTALL)
                                if matches:
                                    for domain in matches:
                                        if '_' in domain:
                                            continue
                                        domains.append(domain.lower())

        for domain in set(domains):
            if self.getTarget().matches(domain, includeChildren=True, includeParents=True):
                evt_type = 'INTERNET_NAME'
            else:
                evt_type = 'AFFILIATE_INTERNET_NAME'

            if self.opts['verify'] and not self.sf.resolveHost(domain):
                self.sf.debug("Host " + domain + " could not be resolved")
                evt_type += '_UNRESOLVED'

            evt = SpiderFootEvent(evt_type, domain, self.__name__, parentEvent)
            self.notifyListeners(evt)

# End of sfp_dnsraw class
