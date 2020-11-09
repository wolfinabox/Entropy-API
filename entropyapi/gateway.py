import os
import json
import asyncio
import websockets
from socket import gaierror
import daiquiri
import random
from datetime import datetime,timedelta
from .utils import RepeatedTimer, get_os,fmt_time,make_dirs,script_dir
from .cache import cache_get,cache_set, cache_set_dict

logger = daiquiri.getLogger('entropy.gateway')
API_VERSION=8

class Gateway_Events(object):
    """Events fired by the gateway, to be received
    """
    async def message_create(self,data:dict):
        """Fired when a message (dm, server message) is received from the gateway
            https://discord.com/developers/docs/resources/channel#message-object

        Args:
            data (dict): The data of the message
        """
        logger.warn('No high-level handler for message_create defined')

class Gateway(object):
    """
    A WebSocket Gateway connection to Discord
    """
    opcodes = {
        0: 'DISPATCH',
        1: 'HEARTBEAT',
        2: 'IDENTIFY',
        3: 'STATUS UPDATE',
        4: 'VOICE STATUS UPDATE',
        6: 'RESUME',
        7: 'RECONNECT',
        8: 'REQUEST GUILD MEMBERS',
        9: 'INVALID SESSION',
        10: 'HELLO',
        11: 'HEARTBEAT ACK'
    }

    close_codes={
        4000:'UNKNOWN ERROR',
        4001:'UNKNOWN OPCODE',
        4002:'DECODE ERROR',
        4003:'NOT AUTHENTICATED',
        4004:'AUTHENTICATION FAILED',
        4005:'ALREADY AUTHENTICATED',
        4007:'INVALID SEQUENCE',
        4008:'RATE LIMITED',
        4009:'SESSION TIMED OUT',
        4010:'INVALID SHARD', #should never apply, but here for completion
        4011:'SHARDING REQURIED', #should never apply, but here for completion
        4012:'INVALID API VER',
        4013:'INVALID INTENT(S)',
        4014:'DISALLOWED INTENT(S)'
    }

    #See info about gateway intents here https://discord.com/developers/docs/topics/gateway#gateway-intents
    intents={
        'GUILDS':1<<0,
        'GUILD_MEMBERS':1<<1,
        'GUILD_BANS':1<<2,
        'GUILD_EMOJIS':1<<3,
        'GUILD_INTEGRATIONS':1<<4,
        'GUILD_WEBHOOKS':1<<5,
        'GUILD_INVITES':1<<6,
        'GUILD_VOICE_STATES':1<<7,
        'GUILD_PRESENCES':1<<8,
        'GUILD_MESSAGES':1<<9,
        'GUILD_MESSAGE_REACTIONS':1<<10,
        'GUILD_MESSAGE_TYPING':1<<11,
        'DIRECT_MESSAGES':1<<12,
        'DIRECT_MESSAGE_REACTIONS':1<<13,
        'DIRECT_MESSAGE_TYPING':1<<14,
    }
    intents['ALL']=sum(intents.values())


    def __init__(self,loop:asyncio.AbstractEventLoop=None,sleep_resume:int=5,compression=None):
        """A gateway connection to the Discord API. The gateway handles all live events.

        Args:
            loop (asyncio.AbstractEventLoop, optional): The async loop to use, otherwise one is created. Defaults to None.
            sleep_resume (int, optional): Amount of time in seconds to sleep between attempts to resume a broken connection. Defaults to 5.
            compression ([type], optional): #TODO remember what this is. Defaults to None.
        """
        self.gateway_events=Gateway_Events()
        self.token:str=None
        self.sleep_resume=sleep_resume
        self.encoding='json'
        self.gateway_url=None
        self.loop: asyncio.AbstractEventLoop = loop or asyncio.get_event_loop()
        self.compression=compression
        self.closed=True
        self.identified=False
        self.session_id=None
        self._websocket: websockets.WebSocketClientProtocol=None
        self.gateway_task:asyncio.Task=None
        self.gateway_intents=self.intents['ALL']#-self.intents['GUILD_PRESENCES']-self.intents['GUILD_MEMBERS']

        #Heartbeat
        self.last_sequence:int=None
        self.heartbeat_ms:int = None
        self.heartbeat_repeater: RepeatedTimer = None
        self.last_heartbeat_ack:int = None
        self.last_heartbeat_sent:int = None

        # Structure
        self.send_queue = []

    async def start(self,token:str,gateway_url:str):
        """Start the gateway

        Args:
            token (str): User token for authenticating
            gateway_url (str): The gateway wss:// url
        """
        #don't start if already started
        if not self.closed:
            return
        self.token=token
        self.gateway_url=gateway_url+f'/?v={API_VERSION}&encoding={self.encoding}'
        logger.debug('Starting gateway...')
        self._websocket = await websockets.connect(self.gateway_url, compression=self.compression)
        #start the main loop
        self.gateway_task=asyncio.create_task(self._runloop(),name='entropy-gateway-loop')


    async def _runloop(self):
        self.closed=False
        logger.info(f'Gateway successfully opened to  {self.gateway_url}')
        while not self._websocket.closed and not self.closed:
            try:
                res=await self._websocket.recv()
                await self._handle_message(json.loads(res))

            except (websockets.ConnectionClosed,OSError) as e:
                await self._handle_close_event(e)

    async def send(self, data: dict):
        """Send date over the gateway.

        Args:
            data (dict): The data to send. Must contain at least {op,d}, and must be serializable as JSON
        """
        # If gateway not open
        if self.closed or not self._websocket or self._websocket.closed:
            logger.warn(f'Send Queued: {data}')
            self.send_queue.append(data)
            return
        # Convert data to json string
        data_string = data if type(data) == str else json.dumps(data)
        # Send
        try:
            await self._websocket.send(data_string)

        except (websockets.ConnectionClosed,OSError) as e:
            #If the message could not be sent, queue it to be sent later
            logger.warn(f'Send Queued: {data_string}')
            self.send_queue.append(data_string)
            #If gateway wasn't already closed, close it
            await self._handle_close_event()
        logger.debug(
            f'SENT: op[{data["op"]}] ({self.opcodes[data["op"]]})')

    async def disconnect(self, code: int = 1000, reason: str = ''):
        """
        Disconnect the gateway.\n
        `reason` The reason to send for the disconnection. Default empty.
        """
        # logger.error('got deaded',code=self._websocket.close_code,reason=self._websocket.close_reason)
        self.closed = True
        if self.heartbeat_repeater:
            self.heartbeat_repeater.stop()
        # self.gateway_task.cancel()
        if not self._websocket.closed:
            await self._websocket.close(code=int(code), reason=reason)
        logger.warn('Gateway disconnected',code=code,reason=reason)

    async def _resume(self):
        """
        Attempt to resume the gateway connection
        """
        reconnect_packet = {
            'op': 6,
            'd': {
                'token': self.token,
                'session_id': self.session_id,
                'seq': self.last_sequence
            }
        }
        # Close codes said to require another identify
        if self._websocket.close_code in (4007, 4009):
            self.identified = False
        while self._websocket.closed:
            logger.debug('Trying to resume gateway...')
            try:
                self._websocket = await websockets.connect(self.gateway_url, compression=self.compression)
            except gaierror as e:
                logger.warn(
                    f'Could not reconncet to "{self.gateway_url}"!',error=e)
                logger.debug(f'Trying again in {self.sleep_resume}s...')
                await asyncio.sleep(self.sleep_resume)
        # Reconnected!
        logger.debug('Reconnected to gateway')
        self.closed=False
        await self.send(reconnect_packet)
        asyncio.create_task(self._runloop(),name='entropy-gateway-loop')
        # Send all queued messages
        while self.send_queue:
            await self.send(self.send_queue.pop(0))

    #Specific message templates
    async def _heartbeat(self, onetime=False):
        """
        Send heartbeat message
        """
        if not onetime and self.last_heartbeat_ack is None:
            logger.error('No heartbeat ACK received!')
            asyncio.ensure_future(self.disconnect('123'))
            asyncio.ensure_future(self._resume())
            return
        self.last_heartbeat_sent = datetime.now()
        await self.send({
            'op': 1,
            'd': self.last_sequence
        })

    async def _identify(self):
        """
        Send an identify packet to Discord
        """
        await self.send({
            'op': 2,
            'd': {
                'token': self.token,
                'intents':self.gateway_intents,
                'properties': {
                    '$os': get_os(),
                    '$browser': 'entropy',
                    '$device': 'entropy'
                    }
            }
        })
        self.identified = True

    #Handlers
    async def _handle_close_event(self,error:websockets.ConnectionClosed):
        """Handle a gateway close event

        Args:
            error (websockets.ConnectionClosed): The close event "error"
        """
        if not self.closed:
            if type(error)==websockets.ConnectionClosed:
                logger.error(f'Gateway closed',code=error.code,reason=error.reason)
            else:
                logger.error(f'Gateway connection error',error=error)

            await self.disconnect()
        await self._resume()

    async def _handle_message(self, data: dict):
        """
        Handle a message sent from the Discord API.\n
        `data` The data received through the gateway.
        """
        logger.debug(f'RECEIVED: op[{data["op"]}] ({self.opcodes.get(data["op"],"UNKNOWN")})'+(
            f', s[{data["s"]}]' if data["s"] is not None else ""))

        # OPCODES
        async def op0():  # Dispatch (most messages)
            await self._handle_event(data)
            

        async def op1():  # Heartbeat Request
            await self._heartbeat(onetime=True)

        async def op7():  # Reconnect Request
            logger.error(f'Gateway closed! (API requested reconnect)')
            await self.disconnect()
            self.identified = False
            await self._resume()

        async def op9():  # Invalid Session
            #If session is resumable
            if data['d']:
                # temp
                await asyncio.sleep(random.randint(1, 5))
                await self._identify()
            else:
                logger.error('Cannot resume from INVALID SESSION!')
                # TEMPORARY (obviously)
                # await self.disconnect(1001)
                raise ConnectionError('Cannot resume from INVALID SESSION')
            ...

        async def op10():  # Hello
            self.heartbeat_ms = data['d']['heartbeat_interval']
            logger.debug(f'Heartbeating every {self.heartbeat_ms/1000}s!')
            # Set up heatbeat repeater
            await self._heartbeat(onetime=True)
            self.heartbeat_repeater = RepeatedTimer(
                float(self.heartbeat_ms)/1000.00, self._heartbeat, self, _loop=self.loop)
            self.heartbeat_repeater.start()
            if not self.identified:
                logger.debug(f'Gateway intents: {self.gateway_intents}')
                await self._identify()

        async def op11():  # Heartbeat ACK
            self.last_heartbeat_ack = datetime.now()
            self.latency = (self.last_heartbeat_ack-self.last_heartbeat_sent)
            logger.debug(f'Latency: {fmt_time(self.latency)}')

        async def op_unhandled():  # Unhandled OPcode
            logger.warn(f'Unhandled opcode "{data["op"]}"!')

        # Handlers for each opcode
        handlers = {
            0: op0,
            1: op1,
            9: op9,
            10: op10,
            11: op11
        }
        self.last_sequence = data['s']
        await handlers.get(data['op'], op_unhandled)()

    async def _handle_event(self, data: dict):
        """
        Handle an event message sent from the Discord API\n
        An event is any packet sent with opcode 0\n
        `data` The whole packet sent
        """
        logger.debug(f'GOT EVENT: {data["t"]}')

        # EVENTS
        async def ready_t():  # Ready
            self.session_id = data['d']['session_id']
            cache_set_dict(data['d'])

        async def resume_t():  # Resume confirmation
            logger.debug('Successfully resumed')

        async def message_create_t():  # Message_Create
            await self.gateway_events.message_create(data['d'])

        async def unknown_t():  # Unknown event
            logger.warn(f'Unhandled event "{data["t"]}"!')
            # if 'DEBUG' not in os.environ or not os.environ['DEBUG']:return
            example_path=os.path.join(script_dir(), 'examples',f'{data["t"]}_EXAMPLE.json')
            make_dirs(example_path)
            if not os.path.exists(example_path):
                json.dump(data, open(example_path,'w'), indent=4)
                logger.warn(f'Data saved to examples/{data["t"]}_EXAMPLE.json')

        handlers = {
            'READY': ready_t,
            'RESUMED': resume_t,
            'MESSAGE_CREATE': message_create_t,
            # 'SESSIONS_REPLACE': sess_repl_t,
        }
        await handlers.get(data['t'], unknown_t)()