from libp2p.abc import IHost
import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator, List, Optional, Tuple, Type, get_type_hints


class ProtocolBase:
    def __init__(self, host: IHost, protocol_id: str):
        self.host = host
        self.protocol_id = protocol_id

    async def add_p2p_handlers(self):
        raise NotImplementedError

    async def remove_p2p_handlers(self):
        raise NotImplementedError

    @classmethod
    def _collect_rpc_handlers(cls) -> None:
        if cls._rpc_handlers is not None:
            return

        cls._rpc_handlers = []
        for method_name, method in inspect.getmembers(
            cls, predicate=inspect.isfunction
        ):
            if method_name.startswith("rpc_"):
                spec = inspect.getfullargspec(method)
                if len(spec.args) < 3:
                    raise ValueError(
                        f"{method_name} is expected to at least three positional arguments "
                        f"(self, request: TInputProtobuf | AsyncIterator[TInputProtobuf], context: P2PContext)"
                    )
                request_arg = spec.args[1]
                hints = get_type_hints(method)
                try:
                    request_type = hints[request_arg]
                    response_type = hints["return"]
                except KeyError:
                    raise ValueError(
                        f"{method_name} is expected to have type annotations "
                        f"like `dht_pb2.FindRequest` or `AsyncIterator[dht_pb2.FindRequest]` "
                        f"for the `{request_arg}` parameter and the return value"
                    )
                request_type, stream_input = cls._strip_iterator_hint(request_type)
                response_type, stream_output = cls._strip_iterator_hint(response_type)

                cls._rpc_handlers.append(
                    RPCHandler(
                        method_name,
                        request_type,
                        response_type,
                        stream_input,
                        stream_output,
                    )
                )

        cls._stub_type = type(
            f"{cls.__name__}Stub",
            (StubBase,),
            {
                handler.method_name: cls._make_rpc_caller(handler)
                for handler in cls._rpc_handlers
            },
        )
