from .httpclient import HTTPClient, HTTPResponse
from .gateway import Gateway,Gateway_Events
from .cache import cache_get,cache_set
import asyncio
import aiohttp
import daiquiri
logger = daiquiri.getLogger('entropy.connection')
DISCORD_EPOCH = 1420070400000
API_VERSION=8

class URLs():
    """URLs associated with the discord api
    """
    main_url = 'https://discordapp.com/api/v'+str(API_VERSION)
    login_path = '/auth/login'
    me_path = '/users/@me'
    gateway_path = '/gateway'
    user_path = '/users/{0}'
    channel_path = '/channels/{0}'
    cdn = 'https://cdn.discordapp.com'


class LoginError(Exception):
    """Exception thrown when the Discord connection was unable to login using the given credentials.
    """
    pass


class EntropyConnection():
    """A Discord connection. Handles all connections to and from the Discord API.
    See documentation here https://discordapp.com/developers/docs/intro
    """
    user_agent = 'Entropy (https://github.com/wolfinabox/Entropy-API)'

    def __init__(self, loop: asyncio.AbstractEventLoop = None):
        """Initialize the connection object

        Args:
            loop (asyncio.AbstractEventLoop, optional): The async loop to use, otherwise one is created. Defaults to None.
        """
        self.loop: asyncio.AbstractEventLoop = loop or asyncio.get_event_loop()
        self.http = HTTPClient(self.loop)
        self.gateway:Gateway=Gateway(self.loop)
        self.token: str = None
        self.id: int = None

    async def start(self, login_info: dict = None, token: str = None, gateway_path:str=None):
        """Start the connection and attempt to log in

        Args:
            login_info (dict, optional): A dictionary containing "email" and "password" keys. Defaults to None.
            token (str, optional): An already-acquired login token. Defaults to None.
            gateway_path (str,optional): An already-acquired path to the gateway, requested from api otherwise. Defaults to None.
        Either login_info or token is required. If both are provided, login_info is prioritized
        """
        if not login_info and not token:
            raise ValueError('Either login_info or token is required.')

        me = None
        try:
            # logging in with email+password
            if login_info:
                if 'email' not in login_info or 'password' not in login_info:
                    raise ValueError(
                        'login_info must contain keys "email" and "password"')

                result, status = \
                    await self.http.request('POST', URLs.main_url, URLs.login_path,
                                            data={**login_info, **{"undelete": False, "captcha_key": None,
                                                                   "login_source": None, "gift_code_sku_id": None}})

                if status == 400:
                    logger.error('Email or Password is incorrect')
                    raise LoginError('Email or Password is incorrect')
                elif status==429:
                    logger.error('Too many login requests')
                    raise LoginError('Too many login requests')
                self.token = result['token']
            # logging in with existing token (from cache, etc)
            else:
                self.token = token

            # test getting user info
            me = await self.get_me(self.token)
            if me:
                logger.info(
                    f'Successfully logged in as "{me["username"]}#{me["discriminator"]}" via {"token" if token else "email/pass"}')
            else:
                logger.error(f'Couldn\'t log in via token')
                raise LoginError(f'Couldn\'t log in via token')

        except (aiohttp.ServerTimeoutError, aiohttp.ClientOSError) as e:
            logger.error(f'Couldn\'t log in',error=e)
            raise LoginError('Couldn\'t log in, see log for details')

        # successfully logged in at this point
        self.id = me['id']
        # start gateway stuff
        gateway_url = gateway_path or (await self.http.request('GET', URLs.main_url, path=URLs.gateway_path))[0]['url']
        if not gateway_path:
            cache_set('gateway_path',gateway_path)
        await self.gateway.start(self.token,gateway_url)
        #TODO on ready??

    async def close(self):
        """Close the connection. Gracefully closes all open connections
        """
        await self.http.close()

    # PROBABLY A TEMP FUNCTION
    async def get_me(self, token):
        """Get the current logged in user from Discord.
        (Probably a temp function)
        """
        resp, stat = await self.http.request('GET', URLs.main_url, path=URLs.me_path, headers={'Authorization': token})
        if stat == 200:
            return resp
        return None
