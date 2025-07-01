#!/usr/bin/env bash

# Get the absolute path of the directory where the script is located
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)


#sudo apt satisfy ffmpeg
sudo apt-get update && sudo apt-get install -y \
                            libasound2-dev \
                            libavcodec-dev \
                            libavdevice-dev \
                            libavformat-dev \
                            libcodec2-dev \
                            libfdk-aac-dev \
                            libglib2.0-dev \
                            libgstreamer1.0-dev \
                            libgtk-3-dev \
                            libjack-jackd2-dev \
                            libmosquitto-dev \
                            libmpg123-dev \
                            libopencore-amrnb-dev \
                            libopencore-amrwb-dev \
                            libopus-dev \
                            libpulse-dev \
                            libsndfile1-dev \
                            libspandsp-dev \
                            libssl-dev \
                            libvpx-dev \
                            libx11-dev \
                            libwebrtc-audio-processing-dev\
                            ffmpeg

cd $SCRIPT_DIR

rm -rf  "${SCRIPT_DIR}/re"
git clone --depth 1 --branch rgnets-custom git@github.com:rgnets/re.git "${SCRIPT_DIR}/re"
cd "${SCRIPT_DIR}/re"

cmake -B build -DCMAKE_BUILD_TYPE=Release #-DSTATIC=ON
cmake --build build -t retest -j
cmake --build build -j
#make RELEASE=1
#
cd build && cpack -G DEB

sudo apt remove -my libre libre-dev ; true
#ls ./re/build/*.deb | xargs -I {} sudo apt install -y {}
sudo apt install -y $(ls ./*.deb)
#sudo apt install ./re/build/*.deb
##sudo cmake --install build
##sudo ldconfig

#

cd $SCRIPT_DIR
#mkdir "${SCRIPT_DIR}/bui"
# sudo apt install make cmake pkg-config git clang ca-certificates libopus-dev libasound2-dev libmosquitto-dev libspandsp-dev libpulse-dev libssl-dev libz-dev
#git@github.com:rgnets/baresip.git
rm -rf  "${SCRIPT_DIR}/baresip"
git clone --depth 1 --branch rgnets-custom git@github.com:rgnets/baresip.git "${SCRIPT_DIR}/baresip"
cd "${SCRIPT_DIR}/baresip"

cmake -B build -DAPP_MODULES_DIR=./modules -DAPP_MODULES="rgrtcpsummary"
cmake --build build -j
cd build && cpack -G DEB
sudo apt remove -my baresip libbaresip libbaresip-dev
sudo apt install -y $(ls ./*.deb)

# baresip baresip-core baresip-ffmpeg baresip-gstreamer baresip-gtk baresip-x11 libdirectfb-1.7-7 libomxil-bellagio-bin libomxil-bellagio0 libopenaptx0 libportaudio2 librem0 libvo-amrwbenc0

#module config will be at /usr/lib/aarch64-linux-gnu/baresip/modules/