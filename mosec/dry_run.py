# Copyright 2023 MOSEC Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Dry run the service."""

from __future__ import annotations

import json
import signal
import sys
import time
from multiprocessing.context import SpawnContext, SpawnProcess
from typing import TYPE_CHECKING, List, Tuple, Union

from mosec.env import env_var_context
from mosec.log import get_internal_logger
from mosec.runtime import PyRuntimeManager, Runtime
from mosec.worker import Worker

if TYPE_CHECKING:
    from multiprocessing.connection import PipeConnection  # type: ignore
    from multiprocessing.synchronize import Event

logger = get_internal_logger()


def dry_run_func(
    worker_cls: type[Worker],
    batch: int,
    receiver: PipeConnection,
    sender: PipeConnection,
    ingress: bool,
    shutdown_notify: Event,
):
    """Dry run simulation function."""
    worker = worker_cls()
    while not shutdown_notify.is_set():
        if receiver.poll(timeout=0.1):
            break

    if shutdown_notify.is_set():
        return

    try:
        data = receiver.recv() if ingress else worker.deserialize(receiver.recv_bytes())
        logger.info("%s received %s", worker, data)
        if batch > 1:
            data = worker.forward([data])[0]
        else:
            data = worker.forward(data)
        logger.info("%s inference result: %s", worker, data)
        data = worker.serialize(data)
        sender.send_bytes(data)
    # pylint: disable=broad-except
    except Exception as err:
        logger.error("get error in %s: %s", worker, err)
        shutdown_notify.set()


class Pool:
    """Process pool for dry run."""

    def __init__(self, process_context: SpawnContext, shutdown_notify: Event):
        """Initialize a process pool.

        Args:
            process_context: server context of spawn process
            shutdown_notify: event of server will shutdown
        """
        self._process_context = process_context
        self._shutdown_notify = shutdown_notify

        self._pool: List[SpawnProcess] = []
        self._sender_pipes: List[PipeConnection] = []
        self._receiver_pipes: List[PipeConnection] = []

    def new_pipe(self):
        """Create new pipe for dry run workers to communicate."""
        receiver, sender = self._process_context.Pipe(duplex=False)
        self._sender_pipes.append(sender)
        self._receiver_pipes.append(receiver)

    def start_worker(self, worker_runtime: Runtime, first: bool):
        """Start the worker process for dry run.

        Args:
            worker_runtime: worker runtime to start
            first: whether the worker is tried to start at first time

        """
        self.new_pipe()
        coordinator = self._process_context.Process(
            target=dry_run_func,
            args=(
                worker_runtime.worker,
                worker_runtime.max_batch_size,
                self._receiver_pipes[-2],
                self._sender_pipes[-1],
                first,
                self._shutdown_notify,
            ),
            daemon=True,
        )

        with env_var_context(worker_runtime.env, 0):
            coordinator.start()

        self._pool.append(coordinator)

    def probe_worker_liveness(self) -> Tuple[Union[int, None], Union[int, None]]:
        """Check every worker is running/alive.

        Returns:
            index: index of the first failed worker
            exitcode: exitcode of the first failed worker

        """
        for i, process in enumerate(self._pool):
            if process.exitcode is not None:
                return i, process.exitcode
        return None, None

    def wait_all(self) -> Tuple[Union[int, None], Union[int, None]]:
        """Blocking until all worker to end or one failed.

        Returns:
            index: index of the first failed worker
            exitcode: exitcode of the first failed worker

        """
        for i, process in enumerate(self._pool):
            process.join()
            if process.exitcode != 0:
                return i, process.exitcode
        return None, None

    def first_last_pipe(self):
        """Get first sender and last receiver pipes."""
        return self._sender_pipes[0], self._receiver_pipes[-1]


class DryRunner:
    """Dry run the full stage.

    If examples are provided in the ingress :py:class:`Worker <mosec.worker.Worker>`,
    they will be used to pass through all the stages.

    For each stage, there will be only 1 worker. If `env` is provided during
    :py:meth:`append_worker <mosec.server.Server.append_worker>`, the 1st one
    will be used.
    """

    def __init__(self, manager: PyRuntimeManager):
        """Init dry runner."""
        logger.info("init dry runner for %s", manager.workers)

        self._manager = manager
        self._process_context: SpawnContext = SpawnContext()
        self._shutdown_notify: Event = self._process_context.Event()
        self._pool = Pool(self._process_context, self._shutdown_notify)

        signal.signal(signal.SIGTERM, self.terminate)
        signal.signal(signal.SIGINT, self.terminate)

    def terminate(self, signum, framestack):
        """Terminate the dry run."""
        logger.info("received terminate signal [%s] %s", signum, framestack)
        self._shutdown_notify.set()

    def run(self):
        """Execute thr dry run process."""
        self._pool.new_pipe()
        for i, worker_runtime in enumerate(self._manager):
            self._pool.start_worker(worker_runtime, i == 0)

        logger.info("dry run init successful")
        self.warmup()

        logger.info("wait for worker init done")
        if not self._shutdown_notify.is_set():
            self._shutdown_notify.set()

        failed, exitcode = self._pool.wait_all()
        if failed is not None:
            logger.warning(
                "detect %s with abnormal exit code %d",
                self._manager.workers[failed],
                exitcode,
            )
            sys.exit(exitcode)
        logger.info("dry run exit")

    def warmup(self):
        """Warmup the service.

        If neither `example` nor `multi_examples` is provided, it will only
        init the worker class.
        """
        ingress = self._manager.workers[0]
        example = None
        if ingress.example:
            example = ingress.example
        elif ingress.multi_examples:
            assert isinstance(ingress.multi_examples, list), (
                "`multi_examples` " "should be a list of data"
            )
            example = ingress.multi_examples[0]

        if not example:
            logger.info("cannot find the example in the 1st stage worker, skip warmup")
            return

        sender, receiver = self._pool.first_last_pipe()
        start_time = time.perf_counter()
        sender.send(example)

        while not self._shutdown_notify.is_set():
            if receiver.poll(0.1):
                break
            # liveness probe
            failed, exitcode = self._pool.probe_worker_liveness()
            if failed is not None:
                logger.warning(
                    "worker %s exit with code %d",
                    self._manager.workers[failed],
                    exitcode,
                )
                self._shutdown_notify.set()
                break

        if self._shutdown_notify.is_set():
            sys.exit(1)

        res = receiver.recv_bytes()
        duration = time.perf_counter() - start_time
        logger.info(
            "dry run result: %s",
            json.dumps(
                {
                    "request": example,
                    "result_size": len(res),
                    "warmup_duration": duration,
                }
            ),
        )
