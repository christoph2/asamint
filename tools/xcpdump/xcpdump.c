/* SPDX-License-Identifier: (GPL-2.0-only OR BSD-3-Clause) */
/*
 * xcpdump.c - dump and explain ASAM MC-1 XCP protocol CAN frames
 *
 * Copyright (c) 2008 Volkswagen Group Electronic Research
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. Neither the name of Volkswagen nor the names of its contributors
 *    may be used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * Alternatively, provided that this notice is retained in full, this
 * software may be distributed under the terms of the GNU General
 * Public License ("GPL") version 2, in which case the provisions of the
 * GPL apply INSTEAD OF those given above.
 *
 * The provided data structures and external interfaces from this code
 * are not restricted to be used by modules with a GPL compatible license.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH
 * DAMAGE.
 *
 * Send feedback to <linux-can@vger.kernel.org>
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <libgen.h>
#include <time.h>
#include <strings.h>

#include <net/if.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/ioctl.h>

#include <linux/can.h>
#include <linux/can/raw.h>
#include <linux/sockios.h>
#include "terminal.h"

#include "xcp.h"

#define NO_CAN_ID 0xFFFFFFFFU

const int canfd_on = 1;


void print_usage(char *prg)
{
        fprintf(stderr, "\nUsage: %s [options] <CAN interface>\n", prg);
        fprintf(stderr, "Options:\n");
        fprintf(stderr, "         -s <can_id>  (source can_id. Use 8 digits for extended IDs)\n");
        fprintf(stderr, "         -d <can_id>  (destination can_id. Use 8 digits for extended IDs)\n");
        fprintf(stderr, "         -x <addr>    (extended addressing mode. Use 'any' for all addresses)\n");
        fprintf(stderr, "         -X <addr>    (extended addressing mode (rx addr). Use 'any' for all)\n");
        fprintf(stderr, "         -c           (color mode)\n");
        fprintf(stderr, "         -a           (print data also in ASCII-chars)\n");
        fprintf(stderr, "         -t <type>    (timestamp: (a)bsolute/(d)elta/(z)ero/(A)bsolute w date)\n");
        fprintf(stderr, "\nCAN IDs and addresses are given and expected in hexadecimal values.\n");
        fprintf(stderr, "\nUDS output contains a flag which provides information about the type of the \n");
        fprintf(stderr, "message.\n\n");
        fprintf(stderr, "Flags:\n");
        fprintf(stderr, "       [SRQ]  = Service Request\n");
        fprintf(stderr, "       [PSR]  = Positive Service Response\n");
        fprintf(stderr, "       [NRC]  = Negative Response Code\n");
        fprintf(stderr, "       [???]  = Unknown (not specified)\n");
        fprintf(stderr, "\n");
}


int main(int argc, char **argv)
{
        int s;
        struct sockaddr_can addr;
        struct can_filter rfilter[2];
        struct canfd_frame frame;
        int nbytes, i;
        canid_t src = NO_CAN_ID;
        canid_t dst = NO_CAN_ID;
        int ext = 0;
        int extaddr = 0;
        int extany = 0;
        int rx_ext = 0;
        int rx_extaddr = 0;
        int rx_extany = 0;
        int asc = 0;
        int color = 0;
        int timestamp = 0;
        int datidx = 0;
        struct timeval tv, last_tv;
        int opt;
        XcpMessage message;

        last_tv.tv_sec  = 0;
        last_tv.tv_usec = 0;

        while ((opt = getopt(argc, argv, "s:d:ax:X:ct:u?")) != -1) {
                switch (opt) {
                case 's':
                        src = strtoul(optarg, (char **)NULL, 16);
                        if (strlen(optarg) > 7)
                                src |= CAN_EFF_FLAG;
                        break;

                case 'd':
                        dst = strtoul(optarg, (char **)NULL, 16);
                        if (strlen(optarg) > 7)
                                dst |= CAN_EFF_FLAG;
                        break;

                case 'c':
                        color = 1;
                        break;

                case 'a':
                        asc = 1;
                        break;

                case 'x':
                        ext = 1;
                        if (!strncmp(optarg, "any", 3))
                                extany = 1;
                        else
                                extaddr = strtoul(optarg, (char **)NULL, 16) & 0xFF;
                        break;

                case 'X':
                        rx_ext = 1;
                        if (!strncmp(optarg, "any", 3))
                                rx_extany = 1;
                        else
                                rx_extaddr = strtoul(optarg, (char **)NULL, 16) & 0xFF;
                        break;

                case 't':
                        timestamp = optarg[0];
                        if ((timestamp != 'a') && (timestamp != 'A') &&
                            (timestamp != 'd') && (timestamp != 'z')) {
                                printf("%s: unknown timestamp mode '%c' - ignored\n",
                                       basename(argv[0]), optarg[0]);
                                timestamp = 0;
                        }
                        break;
                case '?':
                        print_usage(basename(argv[0]));
                        exit(0);
                        break;

                default:
                        fprintf(stderr, "Unknown option %c\n", opt);
                        print_usage(basename(argv[0]));
                        exit(1);
                        break;
                }
        }

        if (rx_ext && !ext) {
                print_usage(basename(argv[0]));
                exit(0);
        }

        if ((argc - optind) != 1 || src == NO_CAN_ID || dst == NO_CAN_ID) {
                print_usage(basename(argv[0]));
                exit(0);
        }

        if ((s = socket(PF_CAN, SOCK_RAW, CAN_RAW)) < 0) {
                perror("socket");
                return 1;
        }

        /* try to switch the socket into CAN FD mode */
        setsockopt(s, SOL_CAN_RAW, CAN_RAW_FD_FRAMES, &canfd_on, sizeof(canfd_on));

        if (src & CAN_EFF_FLAG) {
                rfilter[0].can_id   = src & (CAN_EFF_MASK | CAN_EFF_FLAG);
                rfilter[0].can_mask = (CAN_EFF_MASK|CAN_EFF_FLAG|CAN_RTR_FLAG);
        } else {
                rfilter[0].can_id   = src & CAN_SFF_MASK;
                rfilter[0].can_mask = (CAN_SFF_MASK|CAN_EFF_FLAG|CAN_RTR_FLAG);
        }

        if (dst & CAN_EFF_FLAG) {
                rfilter[1].can_id   = dst & (CAN_EFF_MASK | CAN_EFF_FLAG);
                rfilter[1].can_mask = (CAN_EFF_MASK|CAN_EFF_FLAG|CAN_RTR_FLAG);
        } else {
                rfilter[1].can_id   = dst & CAN_SFF_MASK;
                rfilter[1].can_mask = (CAN_SFF_MASK|CAN_EFF_FLAG|CAN_RTR_FLAG);
        }

        setsockopt(s, SOL_CAN_RAW, CAN_RAW_FILTER, &rfilter, sizeof(rfilter));

        addr.can_family = AF_CAN;
        addr.can_ifindex = if_nametoindex(argv[optind]);

        if (bind(s, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
                perror("bind");
                return 1;
        }

        while (1) {
                nbytes = read(s, &frame, sizeof(frame));
                if (nbytes < 0) {
                        perror("read");
                        return 1;
                } else if (nbytes != CAN_MTU && nbytes != CANFD_MTU) {
                        fprintf(stderr, "read: incomplete CAN frame %zu %d\n", sizeof(frame), nbytes);
                        return 1;
                } else {

                        if (frame.can_id == src && ext && !extany && extaddr != frame.data[0])
                                continue;

                        if (frame.can_id == dst && rx_ext && !rx_extany && rx_extaddr != frame.data[0])
                                continue;

                        if (color)
                                printf("%s", (frame.can_id == src)? FGRED:FGBLUE);

                        if (timestamp) {
                                ioctl(s, SIOCGSTAMP, &tv);


                                switch (timestamp) {

                                case 'a': /* absolute with timestamp */
                                        printf("(%ld.%06ld) ", tv.tv_sec, tv.tv_usec);
                                        break;

                                case 'A': /* absolute with date */
                                {
                                        struct tm tm;
                                        char timestring[25];

                                        tm = *localtime(&tv.tv_sec);
                                        strftime(timestring, 24, "%Y-%m-%d %H:%M:%S", &tm);
                                        printf("(%s.%06ld) ", timestring, tv.tv_usec);
                                }
                                break;

                                case 'd': /* delta */
                                case 'z': /* starting with zero */
                                {
                                        struct timeval diff;

                                        if (last_tv.tv_sec == 0)   /* first init */
                                                last_tv = tv;
                                        diff.tv_sec  = tv.tv_sec  - last_tv.tv_sec;
                                        diff.tv_usec = tv.tv_usec - last_tv.tv_usec;
                                        if (diff.tv_usec < 0)
                                                diff.tv_sec--, diff.tv_usec += 1000000;
                                        if (diff.tv_sec < 0)
                                                diff.tv_sec = diff.tv_usec = 0;
                                        printf("(%ld.%06ld) ", diff.tv_sec, diff.tv_usec);

                                        if (timestamp == 'd')
                                                last_tv = tv; /* update for delta calculation */
                                }
                                break;

                                default: /* no timestamp output */
                                        break;
                                }
                        }

                        if (frame.can_id & CAN_EFF_FLAG)
                                printf(" %s  %8X", argv[optind], frame.can_id & CAN_EFF_MASK);
                        else
                                printf(" %s  %3X", argv[optind], frame.can_id & CAN_SFF_MASK);

                        if (ext)
                                printf("{%02X}", frame.data[0]);

                        if (nbytes == CAN_MTU)
                                printf("  [%d]  ", frame.len);
                        else
                                printf(" [%02d]  ", frame.len);
                        datidx = 0;

                        message.src = src;
                        message.dst = dst;
                        message.frame = &frame;

                        print_xcp_message(&message);

                        if (datidx && frame.len > datidx) {
                                printf(" ");
                                for (i = datidx; i < frame.len; i++) {
                                        printf("%02X ", frame.data[i]);
                                }

                                if (asc) {
                                        printf("%*s", ((7-ext) - (frame.len-datidx))*3 + 5 ,
                                               "-  '");
                                        for (i = datidx; i < frame.len; i++) {
                                                printf("%c",((frame.data[i] > 0x1F) &&
                                                             (frame.data[i] < 0x7F))?
                                                       frame.data[i] : '.');
                                        }
                                        printf("'");
                                }
                        }

                        if (color)
                                printf("%s", ATTRESET);
                        printf("\n");
                        fflush(stdout);
                }
        }

        close(s);

        return 0;
}

