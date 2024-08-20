from __future__ import annotations

import inspect
import weakref
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Callable

from typing_extensions import Self

from ..intervention import InterventionProxy
from ..tracing import protocols
from ..tracing.Bridge import Bridge
from ..tracing.Graph import Graph
from .backends import Backend, BridgeMixin


class GraphBasedContext(AbstractContextManager, BridgeMixin):

    def __init__(
        self,
        backend: Backend,
        graph: Graph = None,
        bridge: Bridge = None,
        **kwargs,
    ) -> None:

        self.backend = backend

        self.graph: Graph = Graph(**kwargs) if graph is None else graph

        if bridge is not None:

            bridge.add(self.graph)

    def apply(
        self,
        target: Callable,
        *args,
        validate: bool = False,
        **kwargs,
    ) -> InterventionProxy:
        """Helper method to directly add a function to the intervention graph.

        Args:
            target (Callable): Function to apply
            validate (bool): If to try and run this operation in FakeMode to test it out and scan it.

        Returns:
            InterventionProxy: Proxy of applying that function.
        """
        return self.graph.create(
            target=target,
            proxy_value=inspect._empty if validate else None,
            args=args,
            kwargs=kwargs,
        )

    def exit(self) -> InterventionProxy:
        """Exits the execution of a sequential intervention graph.

        Returns:
            InterventionProxy: Proxy of the EarlyStopProtocol node.
        """

        if self.graph.sequential:
            return protocols.EarlyStopProtocol.add(self.graph)
        else:
            raise Exception(
                "Early exit is only supported for sequential graph-based contexts."
            )

    def log(self, *data: Any) -> None:
        """Adds a node via .apply to print the value of a Node.

        Args:
            data (Any): Data to print.
        """
        self.apply(print, *data)

    def vis(self, **kwargs) -> None:
        """
        Helper method to save a visualization of the current state of the intervention graph.
        """

        self.graph.vis(**kwargs)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if isinstance(exc_val, BaseException):
            raise exc_val

        self.backend(self)

    ### BACKENDS ########

    def local_backend_execute(self) -> None:

        try:
            self.graph.reset()
            self.graph.execute()
        except protocols.EarlyStopProtocol.EarlyStopException as e:
            raise e
        finally:
            graph = self.graph
            graph.alive = False

            if not isinstance(graph, weakref.ProxyType):
                self.graph = weakref.proxy(graph)

    def bridge_backend_handle(self, bridge: Bridge) -> None:

        bridge.pop_graph()

        protocols.LocalBackendExecuteProtocol.add(self, bridge.peek_graph())

        self.graph = weakref.proxy(self.graph)
