
#if !defined(__REKORDER_HPP)
#define __REKORDER_HPP


#include <cassert>

#include <functional>
#include <fstream>
#include <iostream>
#include <map>
#include <vector>


class XcpLogFileReader {
public:

    XcpLogFileReader() = delete;

    explicit XcpLogFileReader(const std::string& file_name) {
        m_file = new std::fstream(file_name, std::fstream::out | std::fstream::binary | std::fstream::trunc);
    }

    ~XcpLogFileReader() {
        m_file->close();
    }

protected:

private:
    std::fstream * m_file;
    bool is_closed { true };

};

#if 0

class XcpLogFileReader:
    def __init__(self, file_name):
        self._is_closed = True
        try:
            self._log_file = open("{}{}".format(file_name, FILE_EXTENSION), "r+b")
        except Exception as e:
            raise
        else:
            self._mapping = mmap.mmap(self._log_file.fileno(), 0)

        self._is_closed = False
        magic, _, _, _, self.num_containers, self.total_record_count, self.total_size_compressed, self.total_size_uncompressed = (
            FILE_HEADER_STRUCT.unpack(self.get(0, FILE_HEADER_STRUCT.size))
        )
        if magic != MAGIC:
            raise XcpLogFileParseError("Invalid file magic: '{}'.".format(magic))

    def __del__(self):
        if not self._is_closed:
            self.close()

    @property
    def frames(self):
        offset = FILE_HEADER_STRUCT.size
        for _ in range(self.num_containers):
            record_count, size_compressed, size_uncompressed = CONTAINER_HEADER_STRUCT.unpack(self.get(offset, CONTAINER_HEADER_STRUCT.size))
            offset += CONTAINER_HEADER_STRUCT.size
            uncompressed_data = memoryview(lz4block.decompress(self.get(offset, size_compressed)))
            frame_offset = 0
            for _ in range(record_count):
                category, counter, timestamp, frame_length = DAQ_RECORD_STRUCT.unpack(
                    uncompressed_data[frame_offset : frame_offset + DAQ_RECORD_STRUCT.size]
                )
                frame_offset += DAQ_RECORD_STRUCT.size
                frame_data = uncompressed_data[frame_offset : frame_offset + frame_length] # .tobytes()
                frame_offset += len(frame_data)
                frame = DAQRecord(category, counter, timestamp, frame_data)
                yield frame
            offset += size_compressed

    def get(self, address: int, length: int):
        return self._mapping[address : address + length]

    def close(self):
        if hasattr(self, "self._mapping"):
            self._mapping.close()
        self._log_file.close()
        self._is_closed = True

    @property
    def compression_ratio(self):
        if self.total_size_compressed:
            return self.total_size_uncompressed / self.total_size_compressed
#endif

#endif // __REKORDER_HPP

