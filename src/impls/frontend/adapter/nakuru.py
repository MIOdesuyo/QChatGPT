import typing
import logging

import nakuru
import nakuru.entities.components as nkc
import mirai

from src.models.frontend.adapter.interface import MessageInterface
from src.models.system import config as cfg

from ....models.frontend.adapter import interface
from ....models.system import config as cfg
from ....runtime import module
from ....models.entities import forward, query as querymodule


gocqhttp_params = cfg.ConfigEntry(
    "MessageInterface.yaml",
    "gocqhttp_params",
    {
        "host": "localhost",
        "port": 6700,
        "http_port": 5700,
        "token": ""
    },
    """# 使用nakuru-project框架连接go-cqhttp的配置
# host: go-cqhttp的地址
# port: go-cqhttp的正向websocket端口
# http_port: go-cqhttp的正向http端口
# token: 若在go-cqhttp的config.yml设置了access_token, 则填写此处"""
)


class NakuruProjectMessageConverter:
    """消息转换器"""
    @staticmethod
    def yiri2target(message_chain: mirai.MessageChain) -> list:
        msg_list = []
        if type(message_chain) is mirai.MessageChain:
            msg_list = message_chain.__root__
        elif type(message_chain) is list:
            msg_list = message_chain
        else:
            raise Exception("Unknown message type: " + str(message_chain) + str(type(message_chain)))
        
        nakuru_msg_list = []
        
        # 遍历并转换
        for component in msg_list:
            if type(component) is mirai.Plain:
                nakuru_msg_list.append(nkc.Plain(component.text, False))
            elif type(component) is mirai.Image:
                if component.url is not None:
                    nakuru_msg_list.append(nkc.Image.fromURL(component.url))
                elif component.base64 is not None:
                    nakuru_msg_list.append(nkc.Image.fromBase64(component.base64))
                elif component.path is not None:
                    nakuru_msg_list.append(nkc.Image.fromFileSystem(component.path))
            elif type(component) is mirai.Face:
                nakuru_msg_list.append(nkc.Face(id=component.face_id))
            elif type(component) is mirai.At:
                nakuru_msg_list.append(nkc.At(qq=component.target))
            elif type(component) is mirai.AtAll:
                nakuru_msg_list.append(nkc.AtAll())
            elif type(component) is mirai.Voice:
                if component.url is not None:
                    nakuru_msg_list.append(nkc.Record.fromURL(component.url))
                elif component.path is not None:
                    nakuru_msg_list.append(nkc.Record.fromFileSystem(component.path))
            elif type(component) is forward.Forward:
                # 转发消息
                yiri_forward_node_list = component.node_list
                nakuru_forward_node_list = []

                # 遍历并转换
                for yiri_forward_node in yiri_forward_node_list:
                    try:
                        content_list = NakuruProjectMessageConverter.yiri2target(yiri_forward_node.message_chain)
                        nakuru_forward_node = nkc.Node(
                            name=yiri_forward_node.sender_name,
                            uin=yiri_forward_node.sender_id,
                            time=int(yiri_forward_node.time.timestamp()) if yiri_forward_node.time is not None else None,
                            content=content_list
                        )
                        nakuru_forward_node_list.append(nakuru_forward_node)
                    except Exception as e:
                        import traceback
                        traceback.print_exc()

                nakuru_msg_list.append(nakuru_forward_node_list)
            else:
                nakuru_msg_list.append(nkc.Plain(str(component)))
        
        return nakuru_msg_list

    @staticmethod
    def target2yiri(message_chain: typing.Any, message_id: int = -1) -> mirai.MessageChain:
        """将Yiri的消息链转换为YiriMirai的消息链"""
        assert type(message_chain) is list

        yiri_msg_list = []
        import datetime
        # 添加Source组件以标记message_id等信息
        yiri_msg_list.append(mirai.models.message.Source(id=message_id, time=datetime.datetime.now()))
        for component in message_chain:
            if type(component) is nkc.Plain:
                yiri_msg_list.append(mirai.Plain(text=component.text))
            elif type(component) is nkc.Image:
                yiri_msg_list.append(mirai.Image(url=component.url))
            elif type(component) is nkc.Face:
                yiri_msg_list.append(mirai.Face(face_id=component.id))
            elif type(component) is nkc.At:
                yiri_msg_list.append(mirai.At(target=component.qq))
            elif type(component) is nkc.AtAll:
                yiri_msg_list.append(mirai.AtAll())
            else:
                pass
        logging.debug("转换后的消息链: " + str(yiri_msg_list))
        chain = mirai.MessageChain(yiri_msg_list)
        return chain


class NakuruProjectEventConverter:
    """事件转换器"""
    @staticmethod
    def yiri2target(event: typing.Type[mirai.Event]):
        if event is mirai.GroupMessage:
            return nakuru.GroupMessage
        elif event is mirai.FriendMessage:
            return nakuru.FriendMessage
        else:
            raise Exception("未支持转换的事件类型: " + str(event))

    @staticmethod
    def target2yiri(event: typing.Any) -> mirai.Event:
        yiri_chain = NakuruProjectMessageConverter.target2yiri(event.message, event.message_id)
        if type(event) is nakuru.FriendMessage:  # 私聊消息事件
            return mirai.FriendMessage(
                sender=mirai.models.entities.Friend(
                    id=event.sender.user_id,
                    nickname=event.sender.nickname,
                    remark=event.sender.nickname
                ),
                message_chain=yiri_chain,
                time=event.time
            )
        elif type(event) is nakuru.GroupMessage:  # 群聊消息事件
            permission = "MEMBER"

            if event.sender.role == "admin":
                permission = "ADMINISTRATOR"
            elif event.sender.role == "owner":
                permission = "OWNER"

            import mirai.models.entities as entities
            return mirai.GroupMessage(
                sender=mirai.models.entities.GroupMember(
                    id=event.sender.user_id,
                    member_name=event.sender.nickname,
                    permission=permission,
                    group=mirai.models.entities.Group(
                        id=event.group_id,
                        name=event.sender.nickname,
                        permission=entities.Permission.Member
                    ),
                    special_title=event.sender.title,
                    join_timestamp=0,
                    last_speak_timestamp=0,
                    mute_time_remaining=0,
                ),
                message_chain=yiri_chain,
                time=event.time
            )
        else:
            raise Exception("未支持转换的事件类型: " + str(event))


@module.component(interface.MessageAdapterFactory)
class NakuruAdapterFactory(interface.MessageAdapterFactory):

    @classmethod
    def create(cls, config: cfg.ConfigManager) -> 'NakuruAdapter':
        return NakuruAdapter(config)
    

class NakuruAdapter(interface.MessageInterface):
    """Nakuru适配器
    """
    bot: nakuru.CQHTTP
    bot_account_id: int
    
    message_converter: NakuruProjectMessageConverter
    event_converter: NakuruProjectEventConverter
    
    listener_list: list[dict]
    
    def __init__(
        self,
        config: cfg.ConfigManager
    ):
        params = config.get(gocqhttp_params)
        
        # nakuru库有bug，这个接口没法带access_token，会失败
        # 所以目前自行发请求
        import config
        import requests
        resp = requests.get(
            url="http://{}:{}/get_login_info".format(params['host'], params['http_port']),
            headers={
                'Authorization': "Bearer " + params['token'] if 'token' in params else ""
            },
            timeout=5
        )
        if resp.status_code == 403:
            raise Exception("go-cqhttp拒绝访问，请检查config.py中nakuru_config的token是否与go-cqhttp设置的access-token匹配")
        self.bot_account_id = int(resp.json()['data']['user_id'])
        
    def get_bot_id(self) -> str:
        return str(self.bot_account_id)
        
    def parse_launcher(self, launcher: str) -> tuple[str, int]:
        lspt = launcher.split("_")
        
        return lspt[0], int(lspt[1])
    
    async def send_message(self, target: str, origin_event: mirai.Event, message: mirai.MessageChain):
        
        converted_msg = self.message_converter.yiri2target(message)
        
        # 检查是否有转发消息
        has_forward = False
        for msg in converted_msg:
            if type(msg) is list:  # 转发消息，仅回复此消息组件
                has_forward = True
                converted_msg = msg
                break
        
        target_type, target_id = self.parse_launcher(target)    
        
        if has_forward:
            if target_type == "group":
                await self.bot.sendGroupForwardMessage(int(target_id), converted_msg)
            elif target_type == "person":
                await self.bot.sendPrivateForwardMessage(int(target_id), converted_msg)
            else:
                raise Exception("Unknown target type: " + target_type)
        else:
            if target_type == "group":
                await self.bot.sendGroupMessage(int(target_id), converted_msg)
            elif target_type == "person":
                await self.bot.sendFriendMessage(int(target_id), converted_msg)
            else:
                raise Exception("Unknown target type: " + target_type)
    
    def register_listener(self, event_type: type[mirai.Event], callback: typing.Callable[[mirai.Event], typing.Any]):
    
        logging.debug("注册监听器: " + str(event_type) + " -> " + str(callback))

        # 包装函数
        async def listener_wrapper(app: nakuru.CQHTTP, source: self.event_converter.yiri2target(event_type)):
            callback(self.event_converter.target2yiri(source))

        # 将包装函数和原函数的对应关系存入列表
        self.listener_list.append(
            {
                "event_type": event_type,
                "callable": callback,
                "wrapper": listener_wrapper,
            }
        )

        # 注册监听器
        self.bot.receiver(self.event_converter.yiri2target(event_type).__name__)(listener_wrapper)
        logging.debug("注册完成")
    
    def unregister_listener(
        self,
        event_type: typing.Type[mirai.Event],
        callback: typing.Callable[[mirai.Event], typing.Any]
    ):
        """注销事件监听器
        """
        
        nakuru_event_name = self.event_converter.yiri2target(event_type).__name__

        new_event_list = []

        # 从本对象的监听器列表中查找并删除
        target_wrapper = None
        for listener in self.listener_list:
            if listener["event_type"] == event_type and listener["callable"] == callback:
                target_wrapper = listener["wrapper"]
                self.listener_list.remove(listener)
                break

        if target_wrapper is None:
            raise Exception("未找到对应的监听器")

        for func in self.bot.event[nakuru_event_name]:
            if func.callable != target_wrapper:
                new_event_list.append(func)

        self.bot.event[nakuru_event_name] = new_event_list
        
    async def run(self) -> typing.Generator[querymodule.QueryContext, None, None]:
        return await self.bot.run()
    
    def support_reload(self) -> bool:
        return False
    
    def __del__(self):
        pass
        