import os
import random
import ssl
import sys
import time
import traceback
from urllib.parse import urlparse

import arc
from act.arc import aCTDBArc
from act.condor.aCTDBCondor import aCTDBCondor

from . import aCTConfig, aCTLogger, aCTSignal


class aCTProcess:
    '''
    Base class for all aCT processes. Sets up logging, configuration and ARC
    environment and provides basic start and stop functionality.
    '''

    def __init__(self):

        # Get agent name from /path/to/aCTAgent.py
        self.name = os.path.basename(sys.argv[0])[:-3]
        self.cluster = ''
        clusterhost = ''
        if len(sys.argv) == 2:
            self.cluster = sys.argv[1]
            url = urlparse(self.cluster)
            clusterhost = url.netloc.split(':')[0] if url.netloc else url.path

        # logger
        logname = '%s-%s' % (self.name, clusterhost) if clusterhost else self.name
        self.logger=aCTLogger.aCTLogger(logname, cluster=self.cluster)
        self.log=self.logger()
        self.criticallogger = aCTLogger.aCTLogger('aCTCritical', cluster=self.cluster, arclog=False)
        self.criticallog = self.criticallogger()

        # config
        self.conf=aCTConfig.aCTConfigARC()
        self.tmpdir=str(self.conf.get(['tmp', 'dir']))
        # database
        # TODO: subclasses for arc and condor with respective DBs defined there
        self.db=aCTDBArc.aCTDBArc(self.log)
        self.dbcondor=aCTDBCondor(self.log)

        # ARC Configuration
        # Credentials will be set by ARC agents for each job or set of jobs
        # but for now set default credential in config to keep ARC happy
        cred_type=arc.initializeCredentialsType(arc.initializeCredentialsType.SkipCredentials)
        self.uc=arc.UserConfig(cred_type)
        self.uc.ProxyPath(str(self.conf.get(['voms', 'proxypath'])))
        self.uc.CACertificatesDirectory(str(self.conf.get(["voms", "cacertdir"])))
        timeout=int(self.conf.get(['atlasgiis','timeout']))
        self.uc.Timeout(timeout)

        # start time for periodic restart
        self.starttime=time.time()
        self.log.info("Started %s for cluster %s", self.name, self.cluster)

    def process(self):
        '''
        Called every loop during the main loop. Subclasses must implement this
        method with their specific operations.
        '''
        pass

    def run(self):
        '''
        Main loop
        '''
        try:
            while 1:
                # parse config file
                self.conf.parse()
                # Check if the site is in downtime
                if self.cluster not in self.conf.getList(['downtime', 'item']):
                    # sleep between 5 and 10 seconds
                    time.sleep(5 + random.random()*5)
                    # do class-specific things
                    self.process()
                # restart periodically for gsiftp crash
                ip = int(self.conf.get(['periodicrestart', self.name.lower()]) or 0)
                if ip and time.time()-self.starttime > ip :
                    self.log.info("%s for %s exited for periodic restart", self.name, self.cluster)
                    return
        except aCTSignal.ExceptInterrupt as x:
            self.log.info("Received interrupt %s, exiting", str(x))
        except:
            self.log.critical("*** Unexpected exception! ***")
            self.log.critical(traceback.format_exc())
            self.log.critical("*** Process exiting ***")
            self.criticallog.critical(traceback.format_exc())

    def finish(self):
        '''
        Clean up code when process exits
        '''
        self.db.close()
        self.dbcondor.close()
        self.log.info("Cleanup for cluster %s", self.cluster)
        os._exit(0)

    def getProxySSLContext(self, proxyid):
        # create SSL context authenticated with user's proxy certificate
        proxypath = os.path.join(self.db.proxydir, f"proxiesid{proxyid}")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS)
        context.load_cert_chain(proxypath, keyfile=proxypath)
        _DEFAULT_CIPHERS = (
            'ECDH+AESGCM:DH+AESGCM:ECDH+AES256:DH+AES256:ECDH+AES128:DH+AES:ECDH+HIGH:'
            'DH+HIGH:ECDH+3DES:DH+3DES:RSA+AESGCM:RSA+AES:RSA+HIGH:RSA+3DES:!aNULL:'
            '!eNULL:!MD5'
        )
        context.set_ciphers(_DEFAULT_CIPHERS)
        return context
