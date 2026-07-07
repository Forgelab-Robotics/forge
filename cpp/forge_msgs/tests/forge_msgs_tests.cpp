#include "forge_msgs/forge_msgs.hpp"

#include <cmath>
#include <iostream>
#include <string>
#include <tuple>
#include <vector>

namespace {

int failures = 0;

void Check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << "\n";
    ++failures;
  }
}

template <typename Message>
void CheckRoundTrip(const Message& message, const std::string& name) {
  auto batch = message.ToRecordBatch();
  Check(batch.ok(), name + " ToRecordBatch");
  if (!batch.ok()) return;
  auto back = Message::FromRecordBatch(**batch);
  Check(back.ok(), name + " FromRecordBatch");
  if (!back.ok()) return;
  Check((*back).ToRecordBatch().ok(), name + " returned value is valid");
}

}  // namespace

int main() {
  using namespace forge_msgs;

  CheckRoundTrip(Text{"前进"}, "Text");

  Bytes audio_data;
  for (float value : {0.0f, 0.25f, -0.5f, 1.0f}) {
    auto* bytes = reinterpret_cast<std::uint8_t*>(&value);
    audio_data.insert(audio_data.end(), bytes, bytes + sizeof(float));
  }
  CheckRoundTrip(AudioChunk{16000, 1, "f32le", 4, audio_data}, "AudioChunk");
  Check(!AudioChunk{16000, 2, "s16le", 2, {1, 2, 3}}.Validate().ok(),
        "AudioChunk rejects invalid data length");

  CheckRoundTrip(Image{2, 2, "rgb8", 6, Bytes{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}},
                 "Image");
  CheckRoundTrip(CompressedImage{"jpeg", Bytes{0xff, 0xd8, 0xff, 0xd9}}, "CompressedImage");

  CheckRoundTrip(PointCloud{2, 1, true, {1.0f, 2.0f}, {3.0f, 4.0f}, {5.0f, 6.0f},
                            {}, {255, 0}, {0, 255}, {0, 0}},
                 "PointCloud");
  Check(!PointCloud{1, 1, true, {NAN}, {0.0f}, {0.0f}, {}, {}, {}, {}}.Validate().ok(),
        "PointCloud rejects dense NaN");

  CheckRoundTrip(JointState{{"j1", "j2"}, {1.0, 2.0}, {0.1, 0.2}, {}}, "JointState");
  CheckRoundTrip(JointCommand{{"j1"}, "hybrid", {1.0}, {0.0}, {0.5}, {20.0}, {1.0}},
                 "JointCommand");
  Check(!JointCommand{{"j1"}, "bad", {}, {}, {}, {}, {}}.Validate().ok(),
        "JointCommand rejects invalid mode");

  CheckRoundTrip(LocomotionCommand{0.5, 0.1, 0.2}, "LocomotionCommand");
  Check(!LocomotionCommand{NAN, 0.0, 0.0}.Validate().ok(),
        "LocomotionCommand rejects NaN");

  CheckRoundTrip(PolicyCommand{"default", "start_recording", "rec-001", "{\"path\":\"x\"}"},
                 "PolicyCommand");
  CheckRoundTrip(PolicyCommandStatus{"default", "start_recording", "rec-001",
                                     PolicyCommandStatusValue::Done, "done", "{\"ok\":true}"},
                 "PolicyCommandStatus");
  Check(!PolicyCommand{"default", "Start", "", "{}"}.Validate().ok(),
        "PolicyCommand rejects non snake_case");

  auto pose = Pose::FromXyYaw(1.0, 2.0, 1.5707963267948966, 0.0);
  CheckRoundTrip(pose, "Pose");
  auto [x, y, yaw] = pose.XyYaw();
  Check(x == 1.0 && y == 2.0 && std::abs(yaw - 1.5707963267948966) < 1e-12,
        "Pose XyYaw helper");
  CheckRoundTrip(PoseSet{{"a", "b"}, {1.0, 2.0}, {2.0, 3.0}, {0.0, 0.0},
                         {0.0, 0.0}, {0.0, 0.0}, {0.0, 0.0}, {1.0, 1.0}},
                 "PoseSet");

  CheckRoundTrip(Detection2DSet{{"d0", "d1"}, {"track-7", ""}, {10.5f, 20.0f},
                                {11.0f, 21.0f}, {4.0f, 8.0f}, {5.0f, 9.0f},
                                {0.0f, 0.25f}, {0, 2, 3}, {"person", "worker", "cup"},
                                {0.9f, 0.1f, 0.8f}},
                 "Detection2DSet");
  CheckRoundTrip(Detection2DSet::Empty(), "Detection2DSet empty");

  CheckRoundTrip(Detection3DSet{{"d0"}, {""}, {1.0f}, {2.0f}, {3.0f}, {0.0f}, {0.0f},
                                {0.0f}, {1.0f}, {0.5f}, {0.6f}, {0.7f}, {0, 1},
                                {"box"}, {0.95f}},
                 "Detection3DSet");
  CheckRoundTrip(SegmentationMaskSet{{"m0"}, {"d0"}, {""}, {4}, {5}, {2}, {2},
                                     "mono8", {Bytes{0, 255, 255, 0}}},
                 "SegmentationMaskSet");

  if (failures != 0) {
    std::cerr << failures << " failure(s)\n";
    return 1;
  }
  return 0;
}
