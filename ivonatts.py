#!/usr/bin/env python
# encoding: utf-8

class IvonaTTSException(Exception):
    pass

import datetime
import hashlib
import hmac
import json
import tempfile
import contextlib
import os

try:
    import pygame
except ImportError:
    raise IvonaTTSException("Pygame is not installed !")
try:
    import requests
    requests.packages.urllib3.disable_warnings()
except ImportError:
    raise IvonaTTSException('requests is not installed !')

AmazonDateFormat = '%Y%m%dT%H%M%SZ'
DateFormat = '%Y%m%d'

def start(a,b,c,d,e,f):
    return Voice(a,b,c,d,e,f)


class Voice(object):

    RegionSet, HostSet, SessionSet, AKey, SKey, Paragraph, Sentence,  Gender, Speed, Name, Language = None, None, None, None, None, None, None, None, None, None, None
    SetCodec = "ogg"
    region_options = {'us-east': 'us-east-1','us-west': 'us-west-2','eu-west': 'eu-west-1',}
    algorithm = 'AWS4-HMAC-SHA256'
    signed_headers = 'content-type;host;x-amz-content-sha256;x-amz-date'

    @property
    def region(self):
        return self.RegionSet

    @region.setter
    def region(self, region_name):
        self.RegionSet = self.region_options.get(region_name, 'us-east-1')
        self.HostSet = 'tts.{}.ivonacloud.com'.format(self.RegionSet)

    @property
    def codec(self):
        return self.SetCodec

    @codec.setter
    def codec(self, codec):
        if codec not in ["mp3", "ogg"]:
            raise IvonaTTSException(
                "Invalid codec specified. Please choose 'mp3' or 'ogg'")
        self.SetCodec = codec

    @contextlib.contextmanager
    def use_oggSetCodec(self):
        currentSetCodec = self.codec
        self.codec = "ogg"
        try:
            yield
        finally:
            self.codec = currentSetCodec

    def SaveToOgg(self, Text, filename):
        with self.use_oggSetCodec():
            self.SaveToFile(Text, filename)

    def SaveToFile(self, Text, filename):
        file_extension = ".{codec}".format(codec=self.codec)
        filename += file_extension if not filename.endswith(
            file_extension) else ""
        with open(filename, 'wb') as f:
            self.SaveVoice(Text, f)

    def SaveVoice(self, Text, fp):
        r = self.ContactAmazon('POST', 'tts', 'application/json', '/CreateSpeech', '',self.CreateCallback(Text), self.RegionSet, self.HostSet)
        if r.content.startswith(b'{'): raise IvonaTTSException('Error fetching voice: {}'.format(r.content))
        else: fp.write(r.content)

    def TextToSpeech(self, Text, use_cache=False):
        pygame.mixer.init()
        channel = pygame.mixer.Channel(5)
        if use_cache is False:
            with tempfile.SpooledTemporaryFile() as f:
                with self.use_oggSetCodec():
                    self.SaveVoice(Text, f)
                f.seek(0)
                sound = pygame.mixer.Sound(f)
        else:
            CachedFile = hashlib.md5(Text).hexdigest() + '.ogg'
            speech_cache_dir = os.getcwd() + '/speech_cache/'

            if not os.path.isdir(speech_cache_dir):
                os.makedirs(speech_cache_dir)

            if not os.path.isfile(speech_cache_dir + CachedFile):
                with self.use_oggSetCodec():
                    self.SaveToFile(Text, 'speech_cache/' + CachedFile)

            f = speech_cache_dir + CachedFile
            sound = pygame.mixer.Sound(f)
        channel.play(sound)
        while channel.get_busy():
            pass

    def list_voices(self):
        r = self.ContactAmazon(
            'POST', 'tts', 'application/json', '/ListVoices', '', '',
            self.RegionSet, self.HostSet)
        return r.json()

    def CreateCallback(self, Text):
        return json.dumps({
            'Input': {
                "Type":"application/ssml+xml",
                'Data': Text
            },
            'OutputFormat': {
                'Codec': self.codec.upper()
            },
            'Parameters': {
                'Rate': self.Speed,
                'SentenceBreak': self.Sentence,
                'ParagraphBreak': self.Paragraph
            },
            'Voice': {
                'Name': self.Name,
                'Language': self.Language,
                'Gender': self.Gender
            }
        })

    def ContactAmazon(self, method, service, content_type, canonical_uri, canonical_querystring, request_parameters, region, host):

        # Create date for headers and the credential string
        amazon_date = datetime.datetime.utcnow().strftime(AmazonDateFormat)
        date_stamp = datetime.datetime.utcnow().strftime(DateFormat)

        # Step 1: Create canonical request
        payload_hash = hashlib.sha256(request_parameters.encode('utf-8')).hexdigest()
        canonical_headers = 'content-type:{}\n'.format(content_type)
        canonical_headers += 'host:{}\n'.format(host)
        canonical_headers += 'x-amz-content-sha256:{}\n'.format(payload_hash)
        canonical_headers += 'x-amz-date:{}\n'.format(amazon_date)
        canonical_request = '\n'.join([method, canonical_uri, canonical_querystring, canonical_headers,self.signed_headers, payload_hash])

        # Step 2: Create the string to sign
        credential_scope = '{}/{}/{}/aws4_request'.format(date_stamp, region, service)
        string_to_sign = '\n'.join([self.algorithm, amazon_date, credential_scope, hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()])

        # Step 3: Calculate the signature
        KeyDate = hmac.new(('AWS4{}'.format(self.SKey)).encode('utf-8') , date_stamp.encode('utf-8'), hashlib.sha256).digest()
        KeyRegion = hmac.new(KeyDate, region.encode('utf-8'), hashlib.sha256).digest()
        KeyService = hmac.new(KeyRegion, service.encode('utf-8'), hashlib.sha256).digest()
        KeySigning = hmac.new(KeyService, 'aws4_request'.encode('utf-8'), hashlib.sha256).digest()
        signature = hmac.new( KeySigning, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

        # Step 4: Create the signed packet
        endpoint = 'https://{}{}'.format(host, canonical_uri)
        authorization_header = '{} Credential={}/{}, ' +'SignedHeaders={}, Signature={}'
        authorization_header = authorization_header.format( self.algorithm, self.AKey, credential_scope, self.signed_headers, signature)
        headers = { 'Host': host,
            'Content-type': content_type,
            'X-Amz-Date': amazon_date,
            'Authorization': authorization_header,
            'x-amz-content-sha256': payload_hash,
            'Content-Length': str(len(request_parameters))
        }
        if self.SessionSet is None: self.SessionSet = requests.Session()
        return self.SessionSet.post(endpoint, data=request_parameters, headers=headers)

    def __init__(self, AKey, SKey, Name, Sentence, Paragraph, Speed):
        self.region = 'us-east'
        self.Name = Name
        self.AKey = AKey
        self.SKey = SKey
        self.Speed = Speed
        self.Sentence = Sentence
        self.Paragraph = Paragraph
