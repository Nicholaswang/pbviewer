# Protocol Buffers - Google's data interchange format
# Copyright 2008 Google Inc.
# http://code.google.com/p/protobuf/
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

"""This implementation is modified from google's original Protobuf implementation.
The original author is: robinson@google.com (Will Robinson).
Modified by onesuperclark@gmail.com(onesuper).
"""

import struct
import message

TAG_TYPE_BITS = 3  # Number of bits used to hold type info in a proto tag.
_TAG_TYPE_MASK = (1 << TAG_TYPE_BITS) - 1  # 0x7

# These numbers identify the wire type of a protocol buffer value.
# We use the least-significant TAG_TYPE_BITS bits of the varint-encoded
# tag-and-type to store one of these WIRETYPE_* constants.
# These values must match WireType enum in //net/proto2/public/wire_format.h.
WIRETYPE_VARINT = 0
WIRETYPE_FIXED64 = 1
WIRETYPE_LENGTH_DELIMITED = 2
WIRETYPE_START_GROUP = 3
WIRETYPE_END_GROUP = 4
WIRETYPE_FIXED32 = 5
_WIRETYPE_MAX = 5

# Bounds for various integer types.
INT32_MAX = int((1 << 31) - 1)
INT32_MIN = int(-(1 << 31))
UINT32_MAX = (1 << 32) - 1

INT64_MAX = (1 << 63) - 1
INT64_MIN = -(1 << 63)
UINT64_MAX = (1 << 64) - 1

# "struct" format strings that will encode/decode the specified formats.
FORMAT_UINT32_LITTLE_ENDIAN = '<I'
FORMAT_UINT64_LITTLE_ENDIAN = '<Q'

# We'll have to provide alternate implementations of AppendLittleEndian*() on
# any architectures where these checks fail.
if struct.calcsize(FORMAT_UINT32_LITTLE_ENDIAN) != 4:
    raise AssertionError('Format "I" is not a 32-bit number.')
if struct.calcsize(FORMAT_UINT64_LITTLE_ENDIAN) != 8:
    raise AssertionError('Format "Q" is not a 64-bit number.')


def PackTag(field_number, wire_type):
    """Returns an unsigned 32-bit integer that encodes the field number and
    wire type information in standard protocol message wire format.

    Args:
      field_number: Expected to be an integer in the range [1, 1 << 29)
      wire_type: One of the WIRETYPE_* constants.
    """
    if not 0 <= wire_type <= _WIRETYPE_MAX:
        raise message.EncodeError('Unknown wire type: %d' % wire_type)
    return (field_number << TAG_TYPE_BITS) | wire_type


def UnpackTag(tag):
    """The inverse of PackTag().  Given an unsigned 32-bit number,
    returns a (field_number, wire_type) tuple.
    """
    return (tag >> TAG_TYPE_BITS), (tag & _TAG_TYPE_MASK)


def ZigZagEncode(value):
    """ZigZag Transform:  Encodes signed integers so that they can be
    effectively used with varint encoding.  See wire_format.h for
    more details.
    """
    if value >= 0:
        return value << 1
    return ((value << 1) ^ (~0)) | 0x1


def ZigZagDecode(value):
    """Inverse of ZigZagEncode()."""
    if not value & 0x1:
        return value >> 1
    return (value >> 1) ^ (~0)


# The *ByteSize() functions below return the number of bytes required to
# serialize "field number + type" information and then serialize the value.


def Int32ByteSize(field_number, int32):
    return Int64ByteSize(field_number, int32)


def Int64ByteSize(field_number, int64):
    # Have to convert to uint before calling UInt64ByteSize().
    return UInt64ByteSize(field_number, 0xffffffffffffffff & int64)


def UInt32ByteSize(field_number, uint32):
    return UInt64ByteSize(field_number, uint32)


def UInt64ByteSize(field_number, uint64):
    return _TagByteSize(field_number) + _VarUInt64ByteSizeNoTag(uint64)


def SInt32ByteSize(field_number, int32):
    return UInt32ByteSize(field_number, ZigZagEncode(int32))


def SInt64ByteSize(field_number, int64):
    return UInt64ByteSize(field_number, ZigZagEncode(int64))


def Fixed32ByteSize(field_number, fixed32):
    return _TagByteSize(field_number) + 4


def Fixed64ByteSize(field_number, fixed64):
    return _TagByteSize(field_number) + 8


def SFixed32ByteSize(field_number, sfixed32):
    return _TagByteSize(field_number) + 4


def SFixed64ByteSize(field_number, sfixed64):
    return _TagByteSize(field_number) + 8


def FloatByteSize(field_number, flt):
    return _TagByteSize(field_number) + 4


def DoubleByteSize(field_number, double):
    return _TagByteSize(field_number) + 8


def BoolByteSize(field_number, b):
    return _TagByteSize(field_number) + 1


def EnumByteSize(field_number, enum):
    return UInt32ByteSize(field_number, enum)


def StringByteSize(field_number, string):
    return (_TagByteSize(field_number)
            + _VarUInt64ByteSizeNoTag(len(string))
            + len(string))


def BytesByteSize(field_number, b):
    return StringByteSize(field_number, b)


def GroupByteSize(field_number, message):
    return (2 * _TagByteSize(field_number)  # START and END group.
            + message.ByteSize())


def MessageByteSize(field_number, message):
    return (_TagByteSize(field_number)
            + _VarUInt64ByteSizeNoTag(message.ByteSize())
            + message.ByteSize())


def MessageSetItemByteSize(field_number, msg):
    # First compute the sizes of the tags.
    # There are 2 tags for the beginning and ending of the repeated group, that
    # is field number 1, one with field number 2 (type_id) and one with field
    # number 3 (message).
    total_size = (2 * _TagByteSize(1) + _TagByteSize(2) + _TagByteSize(3))

    # Add the number of bytes for type_id.
    total_size += _VarUInt64ByteSizeNoTag(field_number)

    message_size = msg.ByteSize()

    # The number of bytes for encoding the length of the message.
    total_size += _VarUInt64ByteSizeNoTag(message_size)

    # The size of the message.
    total_size += message_size
    return total_size


# Private helper functions for the *ByteSize() functions above.


def _TagByteSize(field_number):
    """Returns the bytes required to serialize a tag with this field number."""
    # Just pass in type 0, since the type won't affect the tag+type size.
    return _VarUInt64ByteSizeNoTag(PackTag(field_number, 0))


def _VarUInt64ByteSizeNoTag(uint64):
    """Returns the bytes required to serialize a single varint.
    uint64 must be unsigned.
    """
    if uint64 > UINT64_MAX:
        raise message.EncodeError('Value out of range: %d' % uint64)
    bytes = 1
    while uint64 > 0x7f:
        bytes += 1
        uint64 >>= 7
    return bytes
