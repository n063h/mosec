# Copyright 2022 MOSEC Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Example: Using Plasma store with mosec mixin PlasmaShmIPCMixin.

We start a subprocess for the plasma server, and pass the path
to the plasma client which serves as the shm mixin.
We also register the plasma server process as a daemon, so
that when it exits the service is able to gracefully shutdown
and restarted by the orchestrator.
"""

import numpy as np
from pyarrow import plasma  # type: ignore

from mosec import Server, ValidationError, Worker
from mosec.mixin import PlasmaShmIPCMixin


class DataProducer(PlasmaShmIPCMixin, Worker):
    """Sample Data Producer."""

    def forward(self, data: dict) -> np.ndarray:
        try:
            nums = np.random.rand(int(data["size"]))
        except KeyError as err:
            raise ValidationError(err) from err
        return nums


class DataConsumer(PlasmaShmIPCMixin, Worker):
    """Sample Data Consumer."""

    def forward(self, data: np.ndarray) -> dict:
        return {"ipc test data": data.tolist()}


if __name__ == "__main__":
    # 200 Mb store, adjust the size according to your requirement
    with plasma.start_plasma_store(plasma_store_memory=200 * 1000 * 1000) as (
        shm_path,
        shm_process,
    ):
        # configure the plasma service path
        PlasmaShmIPCMixin.set_plasma_path(shm_path)

        server = Server()
        # register this process to be monitored
        server.register_daemon("plasma_server", shm_process)
        server.append_worker(DataProducer, num=2)
        server.append_worker(DataConsumer, num=2)
        server.run()
