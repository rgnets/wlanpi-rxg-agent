import asyncio
import logging
import os
from distutils.fancy_getopt import longopt_pat
from os import PathLike
from pathlib import Path
from typing import Callable, Optional

from util_decorators import async_wrap

from wlanpi_rxg_agent import utils
from wlanpi_rxg_agent.lib.sip_control.custom_baresipy import CustomBaresipy
from wlanpi_rxg_agent.lib.sip_control.mdk_baresip import MdkBareSIP
from wlanpi_rxg_agent.lib.sip_control.sip_test import SipTest


class SipTestBaresip(SipTest):

    def __init__(
        self,
        gateway: str,
        user: str,
        password: str,
        extra_login_args: Optional[str] = None,
        debug: bool = False,
        config_path: Optional[PathLike] = None,
        interface: Optional[str] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing {__name__}")

        self._gateway = gateway
        self._user = user
        self._password = password
        self._debug = debug
        self._extra_login_args = extra_login_args
        self._config_path = config_path
        self._interface = interface
        self.logger.info("SipTestBaresip initialized")

    @staticmethod
    async def deploy_config(dest: PathLike = "/tmp/bs/"):
        """
        Loads baresip.conf from the script's directory and writes it to /tmp/bs.conf.
        """
        logger = logging.getLogger(__name__)
        try:
            # Get the absolute path of the directory containing this script
            script_dir = os.path.dirname(os.path.abspath(__file__))

            # Construct the full path to the source and destination files
            # source_file = os.path.join(script_dir, "baresip.conf")

            if not os.path.exists(dest):
                Path(dest).mkdir(parents=True, exist_ok=True)
                # os.mkdir(dest)

            # Read the content from the source file
            # with open(source_file, "r") as src:
            #     content = src.read()

            content = SipTestBaresip.generate_baresip_config()
            # Manipulate file here if needed.

            # Write the content to the destination file
            with open(f"{dest}/config", "w") as dest_file:
                dest_file.write(content)

            print(f"Successfully deployed config to {dest}")

        except FileNotFoundError:
            logger.error(f"Error: Could not write config", exc_info=True)

        except Exception as e:
            logger.error(f"An error occurred: {e}", exc_info=True)

    async def execute(
        self,
        callee: str,
        post_connect: Optional[str] = None,
        call_timeout: Optional[int] = None,
        summary_callback: Optional[Callable] = None,
    ):
        await MdkBareSIP.setup_pi()  # Set up dummy sound device
        async with MdkBareSIP(
            gateway=self._gateway,
            user=self._user,
            pwd=self._password,
            debug=self._debug,
            extra_login_args=self._extra_login_args,
            config_path=self._config_path,
            interface=self._interface,
            loop=asyncio.get_running_loop(),
        ) as bs:
            self.logger.info(f"Executing test against {callee}")

            loop = asyncio.get_running_loop()
            call_in_progress = loop.create_future()
            test_in_progress = loop.create_future()
            summary_future = loop.create_future()

            @bs.ee.listens_to(str(bs.Events.SUMMARY))
            def handle_rtcp_summary(summary: dict, *_, **__):
                self.logger.info(f"Received RTCP summary: {summary}")
                summary_future.set_result(summary)

            @bs.ee.listens_to(str(bs.Events.ESTABLISHED))
            async def call_established(bs_instance: MdkBareSIP, *_, **__):
                self.logger.info("call established")
                # Wait a moment or two.
                await asyncio.sleep(1)
                if post_connect:
                    bs_instance.send_dtmf(post_connect)

                """ CALL TEST LOGIC HERE"""
                self.logger.warning("Speaking!")
                await asyncio.create_task(
                    async_wrap(bs_instance.speak)(
                        "I am WLAN Pi " + utils.get_hostname()
                    )
                )
                self.logger.warning("Done speaking!")
                # Wait a few seconds, because we're not actually done speaking.
                await asyncio.sleep(1)
                # bs_instance.hang()

                """ END CALL TEST LOGIC """
                # If there's no timeout set, always hang up to prevent holding the call open.
                # You can safely hang up before this.
                if not call_timeout:
                    await asyncio.sleep(5)
                    bs_instance.hang()
                if not (test_in_progress.done() or test_in_progress.cancelled()):
                    test_in_progress.set_result(True)

            @bs.ee.listens_to(str(bs.Events.SESSION_CLOSED))
            def handle_call_ended_abnormally(bs_instance: CustomBaresipy, *_, **__):
                self.logger.info("Call ended abnormally")
                # self.logger.debug((call_in_progress.done(), call_in_progress.cancelled()))
                if not (call_in_progress.done() or call_in_progress.cancelled()):
                    call_in_progress.set_result(False)

            @bs.ee.listens_to(str(bs.Events.TERMINATED))
            def handle_call_ended_normally(bs_instance: CustomBaresipy, *_, **__):
                self.logger.info("Call ended normally")
                # print((call_in_progress.done(), call_in_progress.cancelled()))
                if not (call_in_progress.done() or call_in_progress.cancelled()):
                    call_in_progress.set_result(True)

            bs.call(callee)

            self.logger.info("Waiting for call to end")
            try:
                # Wait for both the test itself to end, and the call.
                # In some cases, the test won't end until the call does, or it is timed out.
                call_futures = asyncio.gather(call_in_progress, test_in_progress)
                if call_timeout:
                    await asyncio.wait_for(call_futures, timeout=call_timeout)
                else:
                    await call_futures
                self.logger.info("Test completed")
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"Call timed out after {call_timeout} seconds. Forcibly hanging up."
                )
                bs.hang()
                if not (call_in_progress.done() or call_in_progress.cancelled()):
                    call_in_progress.cancel(msg="Test timeout reached.")
                if not (test_in_progress.done() or test_in_progress.cancelled()):
                    test_in_progress.cancel(msg="Test timeout reached.")

            try:
                # Wait a few seconds for the summary to appear.
                summary = await asyncio.wait_for(summary_future, timeout=4)
                return summary
            except asyncio.TimeoutError:
                self.logger.warning(
                    f"No summary received after {call_timeout} seconds."
                )
                raise Exception("No summary received after call timeout.")

    @staticmethod
    def generate_baresip_config():

        return """
#
# baresip configuration
#

#------------------------------------------------------------------------------

# SIP
#sip_listen		0.0.0.0:5060
#sip_certificate	cert.pem
sip_cafile		/etc/ssl/certs/ca-certificates.crt
sip_capath		/etc/ssl/certs
#sip_transports		udp,tcp,tls,ws,wss
#sip_trans_def		udp
#sip_verify_server	yes
#sip_verify_client	no
#sip_tls_resumption	all
sip_tos			160
#filter_registrar	udp,tcp,tls,ws,wss

# Call
call_local_timeout	120
call_max_calls		4
call_hold_other_calls	yes
call_accept		no

# Audio
audio_path		/usr/share/baresip
audio_player		alsa,default
; audio_player		aufile,/tmp/call_audio.wav
#audio_source		aufile,/home/wlanpi/thx-ulaw.wav
audio_source		alsa,default
; audio_alert		   aufile,/tmp/call_alert.wav
audio_alert		    alsa,default
ausrc_srate		48000
auplay_srate		48000
#ausrc_channels		0
#auplay_channels	0
#audio_txmode		poll		# poll, thread
audio_level		no
ausrc_format		s16		# s16, float, ..
auplay_format		s16		# s16, float, ..
auenc_format		s16		# s16, float, ..
audec_format		s16		# s16, float, ..
audio_buffer		20-160		# ms
audio_buffer_mode	fixed		# fixed, adaptive
audio_silence		-35.0		# in [dB]
audio_telev_pt		101		# payload type for telephone-event

# Video
#video_source		v4l2,/dev/video0
#video_display		x11,nil
video_size		640x480
video_bitrate		1000000
video_fps		30.00
video_fullscreen	no
videnc_format		yuv420p

# AVT - Audio/Video Transport
rtp_tos			184
rtp_video_tos		136
#rtp_ports		10000-20000
#rtp_bandwidth		512-1024 # [kbit/s]
audio_jitter_buffer_type	fixed		# off, fixed, adaptive
audio_jitter_buffer_delay	5-10		# (min. frames)-(max. packets)
video_jitter_buffer_type	fixed		# off, fixed, adaptive
video_jitter_buffer_delay	5-50		# (min. frames)-(max. packets)
rtp_stats		no
#rtp_timeout		60
#avt_bundle		no
#rtp_rxmode		main

# Network
#dns_server		1.1.1.1:53
#dns_server		1.0.0.1:53
#dns_fallback		8.8.8.8:53
#dns_getaddrinfo		no
#net_interface		eth0

# Play tones
#file_ausrc		aufile
file_srate		48000
#file_channels		1
#file_ausrc /home/wlanpi/thx_ulaw.wav


#------------------------------------------------------------------------------
# Modules

module_path		/usr/lib/aarch64-linux-gnu/baresip/modules/

# UI Modules
module			stdio.so
module			cons.so
module			evdev.so
module			httpd.so

# Audio codec Modules (in order)
#module			opus.so
#module			amr.so
#module			g7221.so
#module			g722.so
#module			g726.so
module			g711.so
#module			l16.so
#module			mpa.so
#module			codec2.so

# Audio filter Modules (in encoding order)
module			auconv.so
module			auresamp.so
#module			vumeter.so
#module			sndfile.so
#module			plc.so
#module			webrtc_aec.so

# Audio driver Modules
module			alsa.so
#module			pulse.so
#module			pipewire.so
#module			jack.so
#module			portaudio.so
#module			aubridge.so
module			aufile.so
#module			ausine.so

# Video codec Modules (in order)
#module			avcodec.so
#module			vp8.so
#module			vp9.so

# Video filter Modules (in encoding order)
#module			selfview.so
#module			snapshot.so
#module			swscale.so
#module			vidinfo.so
#module			avfilter.so

# Video source modules
#module			v4l2.so
#module			vidbridge.so

# Video display modules
#module			directfb.so
#module			x11.so
#module			sdl.so
#module			fakevideo.so

# Audio/Video source modules
#module			avformat.so
#module			gst.so

# Compatibility modules
#module			ebuacip.so
module			uuid.so

# Media NAT modules
module			stun.so
module			turn.so
module			ice.so
#module			natpmp.so
#module			pcp.so

# Media encryption modules
#module			srtp.so
#module			dtls_srtp.so
#module			gzrtp.so


#------------------------------------------------------------------------------
# Application Modules

module_app		account.so
module_app		contact.so
module_app		debug_cmd.so
#module_app		echo.so
#module_app		gtk.so
module_app		menu.so
#module_app		mwi.so
#module_app		presence.so
#module_app		serreg.so
#module_app		syslog.so
#module_app		mqtt.so
#module_app		ctrl_tcp.so
#module_app		ctrl_dbus.so
#module_app		httpreq.so
module_app		netroam.so
module_app      rgrtcpsummary.so


#------------------------------------------------------------------------------
# Module parameters

# DTLS SRTP parameters
#dtls_srtp_use_ec	prime256v1


# UI Modules parameters
#cons_listen		0.0.0.0:5555 # cons - Console UI UDP/TCP sockets

#http_listen		0.0.0.0:8000 # httpd - HTTP Server

#ctrl_tcp_listen		0.0.0.0:4444 # ctrl_tcp - TCP interface JSON

#evdev_device		/dev/input/event0

# Opus codec parameters
opus_bitrate		28000 # 6000-510000
#opus_stereo		yes
#opus_sprop_stereo	yesA
#opus_cbr		no
#opus_inbandfec		no
#opus_dtx		no
#opus_mirror		no
#opus_complexity	10
#opus_application	audio	# {voip,audio}
#opus_samplerate	48000
#opus_packet_loss	10	# 0-100 percent (expected packet loss)

# Opus Multistream codec parameters
#opus_ms_channels	2	#total channels (2 or 4)
#opus_ms_streams	2	#number of streams
#opus_ms_c_streams	2	#number of coupled streams

vumeter_stderr		yes

#jack_connect_ports	yes

# Selfview
video_selfview		window # {window,pip}
#selfview_size		64x64

# Menu
#redial_attempts	0 # Num or <inf>
#redial_delay		5 # Delay in seconds
#ringback_disabled	no
#statmode_default	off
#menu_clean_number	no
#sip_autoanswer_method	rfc5373 # {rfc5373,call-info,alert-info}
#ring_aufile		ring.wav
#callwaiting_aufile	callwaiting.wav
#ringback_aufile	ringback.wav
#notfound_aufile	notfound.wav
#busy_aufile		busy.wav
#error_aufile		error.wav
#sip_autoanswer_aufile	autoanswer.wav
#menu_max_earlyaudio	32
#menu_max_earlyvideo_rx	32
#menu_max_earlyvideo_tx	32
#menu_message_tone	yes

# GTK
#gtk_clean_number	no
#gtk_use_status_icon	yes
gtk_use_window	yes

# avcodec
#avcodec_h264enc	libx264
#avcodec_h264dec	h264
#avcodec_h265enc	libx265
#avcodec_h265dec	hevc
#avcodec_hwaccel	vaapi
#avcodec_profile_level_id 42002a
#avcodec_keyint		10

# vp8
#vp8_enc_threads 1
#vp8_enc_cpuused 16 # range -16..16, greater 0 increases speed over quality

# ctrl_dbus
#ctrl_dbus_use	system		# system, session

# mqtt
#mqtt_broker_host	sollentuna.example.com
#mqtt_broker_port	1883
#mqtt_broker_cafile	/path/to/broker-ca.crt	# set this to enforce TLS
#mqtt_broker_clientid	baresip01	# has to be unique
#mqtt_broker_user	user
#mqtt_broker_password	pass
#mqtt_basetopic		baresip/01

# sndfile
#snd_path		/tmp

# EBU ACIP
#ebuacip_jb_type	fixed	# auto,fixed

# HTTP request module
#httpreq_ca		trusted1.pem
#httpreq_ca		trusted2.pem
#httpreq_dns		1.1.1.1
#httpreq_dns		8.8.8.8
#httpreq_hostname	myserver
#httpreq_cert		cert.pem
#httpreq_key		key.pem

# avformat
#avformat_hwaccel	vaapi
#avformat_inputformat	mjpeg
#avformat_decoder	mjpeg
#avformat_pass_through	yes
#avformat_rtsp_transport	udp

# ice
#ice_policy		all	# all, relay (candidates)
        """

if __name__ == "__main__":

    async def main():
        sip_test = SipTestBaresip(
            gateway="192.168.7.15", user="pi2", password="pitest", debug=True
        )
        await sip_test.execute(callee="1101", post_connect="1234", call_timeout=2)
        print("done!")

    asyncio.get_event_loop().run_until_complete(main())
