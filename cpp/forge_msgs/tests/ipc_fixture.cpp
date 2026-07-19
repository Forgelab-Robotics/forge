#include "forge_msgs/forge_msgs.hpp"

#include <cstdint>
#include <iostream>
#include <string>

namespace {

int Usage() {
  std::cerr << "usage: forge_msgs_ipc_fixture <command> <path>\n"
            << "commands: write/read-{text,audio,classification,keypoint2d,keypoint3d,segmentation}\n";
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

  if (command == "write-classification") {
    auto batch = forge_msgs::Classification{{"person", "vehicle"}, {0.9f, 0.1f}}.ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-classification") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Classification::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->class_id.empty()) {
      std::cout << "0 empty\n";
    } else {
      std::cout << value->class_id.size() << " " << value->class_id.front() << " "
                << value->score.front() << "\n";
    }
    return 0;
  }

  if (command == "write-keypoint2d") {
    auto batch = forge_msgs::Keypoint2DSet{{"person-0"}, {"d0"}, {"track-0"}, {0, 2},
                                           {"left_eye", "right_eye"}, {10.0f, 12.0f},
                                           {20.0f, 20.0f}, {0.9f, 0.8f}}
                     .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-keypoint2d") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Keypoint2DSet::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->instance_id.empty() || value->keypoint_id.empty()) {
      std::cout << value->instance_id.size() << " " << value->keypoint_id.size() << " empty\n";
    } else {
      std::cout << value->instance_id.front() << " " << value->keypoint_id.size() << " "
                << value->x.front() << " " << value->score.front() << "\n";
    }
    return 0;
  }

  if (command == "write-keypoint3d") {
    auto batch = forge_msgs::Keypoint3DSet{{"person-0"}, {"d0"}, {"track-0"}, {0, 1},
                                           {"nose"}, {1.0f}, {2.0f}, {3.0f}, {0.95f}}
                     .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-keypoint3d") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::Keypoint3DSet::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->instance_id.empty() || value->keypoint_id.empty()) {
      std::cout << value->instance_id.size() << " " << value->keypoint_id.size() << " empty\n";
    } else {
      std::cout << value->instance_id.front() << " " << value->keypoint_id.front() << " "
                << value->z.front() << " " << value->score.front() << "\n";
    }
    return 0;
  }

  if (command == "write-segmentation") {
    auto batch = forge_msgs::SegmentationMaskSet{{"m0"}, {"d0"}, {"track-0"}, {4}, {5}, {2}, {2},
                                                 "mono8", {{0, 255, 255, 0}}, {0.98f}}
                     .ToRecordBatch();
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    return WriteBatch(*batch, path);
  }

  if (command == "read-segmentation") {
    auto batch = forge_msgs::ReadIpcStream(path);
    if (!batch.ok()) {
      std::cerr << batch.status().ToString() << "\n";
      return 1;
    }
    auto value = forge_msgs::SegmentationMaskSet::FromRecordBatch(**batch);
    if (!value.ok()) {
      std::cerr << value.status().ToString() << "\n";
      return 1;
    }
    if (value->mask_id.empty()) {
      std::cout << "0 0 empty\n";
    } else {
      std::cout << value->mask_id.front() << " " << value->data.front().size() << " ";
      if (value->score.empty()) {
        std::cout << "empty\n";
      } else {
        std::cout << value->score.front() << "\n";
      }
    }
    return 0;
  }

  return Usage();
}
