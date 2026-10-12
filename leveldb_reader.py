import struct
import cramjam
from pathlib import Path

def read_varint(data, pos):
    result = 0
    shift = 0
    while True:
        if pos >= len(data):
            return result, pos
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7f) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, pos

def decode_block(data):
    """Parses key-value pairs from an uncompressed block."""
    if len(data) < 4:
        return []
    num_restarts = struct.unpack_from('<I', data, len(data) - 4)[0]
    restart_offset = len(data) - 4 - (num_restarts * 4)
    if restart_offset < 0:
        return []

    pos = 0
    kvs = []
    last_key = bytearray()

    while pos < restart_offset:
        shared_len, pos = read_varint(data, pos)
        unshared_len, pos = read_varint(data, pos)
        val_len, pos = read_varint(data, pos)

        if pos + unshared_len + val_len > len(data):
            break

        key_delta = data[pos : pos + unshared_len]
        pos += unshared_len
        value = data[pos : pos + val_len]
        pos += val_len

        key = bytes(last_key[:shared_len] + key_delta)
        last_key = bytearray(key)
        kvs.append((key, value))

    return kvs

def read_block_at(f_data, offset, size):
    block_bytes = f_data[offset : offset + size]
    trailer = f_data[offset + size : offset + size + 5]
    if len(trailer) < 5:
        return b""
    compression_type = trailer[0]
    if compression_type == 0:
        return block_bytes
    elif compression_type == 1:
        try:
            return bytes(cramjam.snappy.decompress_raw(block_bytes))
        except Exception:
            return b""
    return b""

def read_sstable(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()

    if len(data) < 48:
        return []

    footer = data[-48:]
    magic = footer[-8:]
    if magic != bytes.fromhex("57fb808b247547db"):
        return []

    pos = 0
    meta_offset, pos = read_varint(footer, pos)
    meta_size, pos = read_varint(footer, pos)
    index_offset, pos = read_varint(footer, pos)
    index_size, pos = read_varint(footer, pos)

    index_block_uncompressed = read_block_at(data, index_offset, index_size)
    if not index_block_uncompressed:
        return []

    index_kvs = decode_block(index_block_uncompressed)
    
    all_kvs = []
    for idx_key, handle_bytes in index_kvs:
        blk_pos = 0
        blk_offset, blk_pos = read_varint(handle_bytes, blk_pos)
        blk_size, blk_pos = read_varint(handle_bytes, blk_pos)

        data_block = read_block_at(data, blk_offset, blk_size)
        if data_block:
            kvs = decode_block(data_block)
            all_kvs.extend(kvs)

    return all_kvs

def read_leveldb_log(file_path):
    """Parses LevelDB write-ahead log (.log file)."""
    with open(file_path, 'rb') as f:
        data = f.read()

    kvs = []
    pos = 0
    # LevelDB log block size is 32KB (32768)
    while pos + 7 <= len(data):
        crc = struct.unpack_from('<I', data, pos)[0]
        length = struct.unpack_from('<H', data, pos + 4)[0]
        record_type = data[pos + 6]
        pos += 7
        if pos + length > len(data):
            break
        record_data = data[pos : pos + length]
        pos += length

        # Batch header: sequence (8 bytes), count (4 bytes)
        if len(record_data) > 12:
            batch_count = struct.unpack_from('<I', record_data, 8)[0]
            b_pos = 12
            for _ in range(batch_count):
                if b_pos >= len(record_data):
                    break
                val_type = record_data[b_pos]
                b_pos += 1
                if val_type == 1: # kTypeValue
                    k_len, b_pos = read_varint(record_data, b_pos)
                    key = record_data[b_pos : b_pos + k_len]
                    b_pos += k_len
                    v_len, b_pos = read_varint(record_data, b_pos)
                    val = record_data[b_pos : b_pos + v_len]
                    b_pos += v_len
                    kvs.append((key, val))
                elif val_type == 0: # kTypeDeletion
                    k_len, b_pos = read_varint(record_data, b_pos)
                    key = record_data[b_pos : b_pos + k_len]
                    b_pos += k_len
                    # deletion
    return kvs
