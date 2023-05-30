# Copyright 2023 MOSEC Authors
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

"""Provide common useful utils to develop MOSEC."""

from mosec.utils.openapi import make_body, make_response
from mosec.utils.types import parse_cls_func_types, parse_instance_func_types

__all__ = [
    "parse_instance_func_types",
    "parse_cls_func_types",
    "make_body",
    "make_response",
]
