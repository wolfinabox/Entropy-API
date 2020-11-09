import asyncio
import aiohttp
import json
from typing import Any, Union,Tuple,Dict
from datetime import timedelta,datetime
import daiquiri
logger=daiquiri.getLogger('entropy.httpclient')
from .utils import fmt_time

class HTTPResponse:
    """
    Accessor for HTTP responses and json errors from the Discord API\n
    https://discordapp.com/developers/docs/topics/opcodes-and-status-codes#http-http-response-codes
    """
    responses = {
        200: 'OK',
        201: 'CREATED',
        204: 'NO CONTENT',
        304: 'NOT MODIFIED',
        400: 'BAD REQUEST',
        401: 'UNAUTHORIZED',
        403: 'FORBIDDEN',
        404: 'NOT FOUND',
        405: 'METHOD NOT ALLOWED',
        429: 'TOO MANY REQUESTS',
        502: 'GATEWAY UNAVAILABLE'
    }
    json_errors = {
        10001: 'UNKNOWN ACCOUNT',
        10002: 'UNKNOWN APPLICATION',
        10003: 'UNKNOWN CHANNEL',
        10004: 'UNKNOWN GUILD',
        10005: 'UNKNOWN INTEGRATION',
        10006: 'UNKNOWN INVITE',
        10007: 'UNKNOWN MEMBER',
        10008: 'UNKNOWN MESSAGE',
        10009: 'UNKNOWN OVERWRITE',
        10010: 'UNKNOWN PROVIDER',
        10011: 'UNKNOWN ROLE',
        10012: 'UNKNOWN TOKEN',
        10013: 'UNKNOWN USER',
        10014: 'UNKNOWN EMOJI',
        10015: 'UNKNOWN WEBHOOK',
        20001: 'BOTS CANNOT USE THIS ENDPOINT',  # SHOULD NEVER HAPPEN
        20002: 'ONLY BOTS CAN USE THIS ENDPOINT',
        30001: 'MAX GUILDS REACHED (100)',
        30002: 'MAX FRIENDS REACHED (1000)',
        30003: 'MAX PINS REACHED (50)',
        30005: 'MAX ROLES REACHED (250)',
        30010: 'MAX REACTIONS REACHED (20)',
        30013: 'MAX GUILD CHANNELS REACHED (500)',
        40001: 'UNAUTHORIZED',
        50001: 'MISSING ACCESS',
        50002: 'INVALID ACCOUNT TYPE',
        50003: 'CANNOT EXECUTE ACTION ON DM CHANNEL',
        50004: 'WIDGET DISABLED',
        50005: 'CANNOT EDIT MESSAGE AUTHORED BY OTHER USER',
        50006: 'CANNOT SEND EMPTY MESSAGE',
        50007: 'CANNOT SEND MESSAGES TO THIS USER',
        50008: 'CANNOT SEND MESSAGES IN VOICE CHANNEL',
        50009: 'CHANNEL VERIFICATION LEVEL TOO HIGH',
        50010: 'OAUTH2 APP DOES NOT HAVE BOT',  # SHOULD NEVER HAPPEN
        50011: 'OAUTH2 APP LIMIT REACHED',  # SHOULD NEVER HAPPEN
        50012: 'INVALID OAUTH STATE',
        50013: 'MISSING PERMISSIONS',
        50014: 'INVALID AUTH TOKEN',
        50015: 'NOTE IS TOO LONG',
        50016: 'PROVIDED TOO FEW/MANY MESSAGES TO DELETE (<2|>100)',
        50019: 'MESSAGE CAN ONLY BE PINNED TO CHANNEL IT WAS SENT IN',
        50020: 'INVIDE CODE INVALID/TAKEN',
        50021: 'CANNOT EXECUTE ACTION ON SYSTEM MESSAGE',
        50025: 'INVALID OATH2 ACCESS TOKEN',
        50034: 'MESSAGE TOO OLD TO BULK DELETE',
        50035: 'INVALID FORM BODY',
        50036: 'INVITE ACCEPTED TO GUILD APP\'S BOT IS NOT IN',  # SHOULD NEVER HAPPEN
        50041: 'INVALID API VERSION',
        90001: 'REACTION BLOCKED'
    }

class HTTPClient:
    """HTTP client used to make requests to the Discord API (or other endpoints).
    """

    def __init__(self,loop:asyncio.AbstractEventLoop=None,connection_timeout:int=5):
        """Create an HTTP client

        Args:
            loop (asyncio.AbstractEventLoop, optional): The async loop to use, otherwise one is created. Defaults to None.
            connection_timeout (int, optional): The amount of time in seconds to wait before timing out a connection. Defaults to 5.
        """
        self.loop:asyncio.AbstractEventLoop=loop or asyncio.get_event_loop()
        self.connection_timeout=connection_timeout
        self._session=aiohttp.ClientSession(loop=self.loop)

    async def close(self):
        """Close the HTTP client.
        """
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def request(self,method:str,url:str,path:str='',data:dict=None,headers:dict=None,encoding:str='utf-8',return_json:bool=True,**kwargs)->Tuple[Union[Dict[Any,Any],Any,None],int]:
        """Make an HTTP request, and return the result.

        Args:
            method (str): The HTTP method to use (GET, POST, PUT etc)
            url (str): The base URL to request to
            path (str, optional): The path to append to the base url. Defaults to ''.
            data (dict, optional): The data to send with the request. Defaults to None.
            headers (dict, optional): The headers to send with the request. Defaults to None.
            encoding (str, optional): The encoding to use for JSON decoding. Defaults to 'utf-8'.
            return_json (bool, optional): Whether to parse the results into json, or return the raw response. Defaults to True.
            All other **kwargs are passed to aiohttp's request()

        Returns:
            Tuple[Union[Dict[Any,Any],Any,None],int]: The response of the request. This is a dictionary of values, a raw string, or None, and the response code of the request.
        """
        start_time=datetime.now()
        if method.upper() not in ('POST','GET','PUT','DELETE','HEAD','OPTIONS','PATCH'):
            raise ValueError(f"Invalid HTTP request type {method.upper()}, Must be one of {', '.join(('POST','GET','PUT','DELETE','HEAD','OPTIONS','PATCH'))}")
        if not self._session or self._session.closed:
            self._session=aiohttp.ClientSession(loop=self.loop)


        #Construct headers and format data
        if data and type(data)!=str: data=json.dumps(data,separators=(',',':'))
        if not headers: headers={}
        if data and 'Content-Type' not in headers:
            headers['Content-Type']='application/json'
        if 'Content-Length' not in headers:
            headers['Content-Length']=str(len(data)) if data else '0'

        #Make request
        response:aiohttp.ClientResponse=None
        timeout=aiohttp.ClientTimeout(total=self.connection_timeout)
        try:
            response=await self._session.request((method.upper()),url+path,timeout=timeout,data=data,headers=headers,**kwargs)
        except aiohttp.ServerTimeoutError as e:
            raise
        except aiohttp.ClientOSError as e:
            raise
        if return_json:
            result=await response.json(encoding=encoding)
        else:
            result=await response.read()
        end_time=datetime.now()-start_time
        logger.debug(
            f'{method.upper()} request to {url+path} finished with status {response.status} ({HTTPResponse.responses.get(response.status,"???")}). Took {fmt_time(end_time)}')
        return result,response.status
