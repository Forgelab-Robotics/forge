#include "forge_msgs/forge_msgs.hpp"

#include <cstdint>
#include <iostream>
#include <string>

namespace {

int Usage() {
  std::cerr << "usage: forge_msgs_ipc_fixture <write-text|read-text|write-audio|read-audio> <path>\n";
  return 2;
}

int WriteBatch(const std::shared_ptr<arrow::RecordBatch>& batch, const std::string& path) {
  auto status = forge_msgs::WriteIpcStream(*batch, path);
  if (!status.ok()) {
    std::cerr << status.ToString() << "\n";
    return 1;
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) return Usage();

  std::string command = argv[1];
  std::string path = argv[2];

  if (command == "write-text") {
    auto batch = forge_msgs::Text{"cpp hello"}.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-text") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto text = forge_msgs::Text::FromRecordBatch(**batch);
    if (!text.ok()) {
      std::cerr << text.status().ToString() << "\n";
      return 1;
    }
    std::cout << text->text << "\n";
    return 0;
  }

  if (command == "write-audio") {
    forge_msgs::Bytes data;
    for (float value : {0.0f, 0.25f}) {
      auto* bytes = reinterpret_cast<std::uint8_t*>(&value);
      data.insert(data.end(), bytes, bytes + sizeof(float));
    }
    auto batch = forge_msgs::AudioChunk{16000, 1, "f32le", 2, data}.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-audio") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto audio = forge_msgs::AudioChunk::FromRecordBatch(**batch);
    if (!audio.ok()) {
      std::cerr << audio.status().ToString() << "\n";
      return 1;
    }
    std::cout << audio->sample_rate << " " << audio->channels << " "
              << audio->sample_format << " " << audio->frame_count << " "
              << audio->data.size() << "\n";
    return 0;
  }

  return Usage();
}
