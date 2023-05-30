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

"""MOSEC type validation mixin."""

import warnings
from typing import Any, Dict, Tuple

from mosec.errors import ValidationError
from mosec.worker import MOSEC_REF_TEMPLATE, Worker

try:
    import msgspec  # type: ignore
except ImportError:
    warnings.warn("msgpack is required for TypedMsgPackMixin", ImportWarning)


class TypedMsgPackMixin(Worker):
    """Enable request type validation with `msgspec` and serde with `msgpack`."""

    # pylint: disable=no-self-use

    resp_mime_type = "application/msgpack"

    def deserialize(self, data: Any) -> Any:
        """Deserialize and validate request with msgspec."""
        input_typ, _ = self._get_forward_types()
        if not issubclass(input_typ, msgspec.Struct):
            # skip other annotation type
            return super().deserialize(data)

        try:
            return msgspec.msgpack.decode(data, type=input_typ)
        except msgspec.ValidationError as err:
            raise ValidationError(err)  # pylint: disable=raise-missing-from

    def serialize(self, data: Any) -> bytes:
        """Serialize with `msgpack`."""
        return msgspec.msgpack.encode(data)

    def _get_forward_json_schema(
        self,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        input_typ, return_typ = self._get_forward_types()
        (input_schema, return_schema), comp_schema = msgspec.json.schema_components(
            [input_typ, return_typ], MOSEC_REF_TEMPLATE
        )
        return (input_schema, return_schema, comp_schema)
