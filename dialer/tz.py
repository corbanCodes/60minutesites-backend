"""Lead-local time. A calling window means nothing if it is measured on the
server's clock -- 9am in Knoxville is 6am in Los Angeles."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

# North American area code -> IANA zone. Covers the NANP; anything unknown
# falls back to the account's own zone and is flagged, never silently dialled.
AREA_TZ = {}


def _fill(zone, codes):
    for c in codes.split():
        AREA_TZ[c] = zone


_fill("America/New_York", """
201 202 203 207 212 215 216 220 223 229 234 239 240 252 267 272 276 278 283 301
302 304 305 309 312 313 315 317 321 326 330 332 336 339 341 347 351 352 353 364
380 386 401 404 407 410 412 413 419 423 434 440 443 445 447 448 464 470 475 478
484 502 504 508 513 516 517 518 519 540 551 557 561 564 567 570 571 574 579 581
585 586 603 606 607 610 614 616 617 618 626 629 631 636 645 646 647 656 667 673
678 680 681 686 689 703 704 705 706 716 717 718 724 727 729 731 732 734 740 743
747 754 757 762 765 770 772 773 774 781 786 787 802 803 804 807 810 812 813 814
815 819 828 829 835 839 840 843 845 847 848 849 850 854 856 857 859 860 862 863
864 865 872 873 876 878 904 908 912 914 917 919 924 929 930 931 937 939 941 947
948 954 959 971 973 978 980 984 986 989
""")
_fill("America/Chicago", """
205 214 217 224 251 254 256 262 270 281 309 312 314 316 318 319 320 325 331 334
337 346 351 361 364 402 405 409 414 417 430 432 438 440 450 456 463 469 479 480
501 502 504 507 512 515 531 539 557 563 573 580 601 602 605 608 612 615 618 620
630 636 641 651 657 659 660 662 682 701 708 712 713 715 726 737 763 769 773 775
779 785 806 812 815 816 817 830 832 838 847 850 870 872 901 903 913 915 918 920
928 931 936 940 952 956 972 979 985
""")
_fill("America/Denver", """
208 303 307 308 385 406 435 505 575 605 719 720 801 928 970 983
""")
_fill("America/Phoenix", "480 520 602 623 928")
_fill("America/Los_Angeles", """
206 209 213 253 279 310 323 341 350 360 408 415 424 425 442 509 510 530 559 562
564 619 626 628 650 657 661 669 702 707 714 725 747 751 760 775 805 808 818 820
831 840 858 909 916 925 949 951 971 503 541 458 623
""")
_fill("America/Anchorage", "907")
_fill("Pacific/Honolulu", "808")

# Area code -> USPS state, for the per-state overlay.
AREA_STATE = {}


def _fills(state, codes):
    for c in codes.split():
        AREA_STATE.setdefault(c, state)


_fills("CA", "209 213 279 310 323 341 350 408 415 424 442 510 530 559 562 619 626 628 650 657 661 669 707 714 747 751 760 805 818 820 831 840 858 909 916 925 949 951")
_fills("NY", "212 315 332 347 363 516 518 585 607 631 646 680 716 718 838 845 914 917 929 934")
_fills("TX", "210 214 254 281 325 346 361 409 430 432 469 512 682 713 726 737 806 817 830 832 903 915 936 940 945 956 972 979")
_fills("FL", "239 305 321 352 386 407 561 727 754 772 786 813 850 863 904 941 954")
_fills("TN", "423 615 629 731 865 901 931")
_fills("OK", "405 539 572 580 918")
_fills("MD", "227 240 301 410 443 667")
_fills("NJ", "201 551 609 640 732 848 856 862 908 973")
_fills("IL", "217 224 309 312 331 447 464 618 630 708 730 773 779 815 847 872")
_fills("PA", "215 223 267 272 412 445 484 570 582 610 717 724 814 835 878")
_fills("WA", "206 253 360 425 509 564")
_fills("MA", "339 351 413 508 617 774 781 857 978")
_fills("MI", "231 248 269 313 517 586 616 679 734 810 906 947 989")
_fills("MT", "406")
_fills("NH", "603")
_fills("NV", "702 725 775")
_fills("CT", "203 475 860 959")
_fills("MS", "228 601 662 769")


def area_code(e164):
    d = "".join(c for c in str(e164 or "") if c.isdigit())
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d[:3] if len(d) == 10 else ""


def zone_for(e164, fallback="America/New_York"):
    return AREA_TZ.get(area_code(e164), fallback)


def state_for(e164):
    return AREA_STATE.get(area_code(e164), "")


def local_now(zone_name):
    try:
        return datetime.now(ZoneInfo(zone_name))
    except Exception:
        return datetime.now(ZoneInfo("America/New_York"))


def parse_hhmm(s, default=(9, 0)):
    try:
        h, m = str(s).split(":")
        return time(int(h), int(m))
    except Exception:
        return time(*default)


def in_window(zone_name, start="09:00", end="19:00", weekdays=None):
    """weekdays: set of ISO weekday ints (Mon=1..Sun=7). -> (ok, local_dt)"""
    now = local_now(zone_name)
    if weekdays and now.isoweekday() not in weekdays:
        return False, now
    t = now.time()
    return (parse_hhmm(start, (9, 0)) <= t <= parse_hhmm(end, (19, 0))), now


def next_window_open(zone_name, start="09:00", weekdays=None):
    """Naive-UTC datetime of the next moment the window opens."""
    from datetime import timedelta
    now = local_now(zone_name)
    st = parse_hhmm(start, (9, 0))
    cand = now.replace(hour=st.hour, minute=st.minute, second=0, microsecond=0)
    if cand <= now:
        cand = cand + timedelta(days=1)
    for _ in range(8):
        if not weekdays or cand.isoweekday() in weekdays:
            break
        cand = cand + timedelta(days=1)
    return cand.astimezone(timezone.utc).replace(tzinfo=None)


# Hospitality: owners and GMs are reachable between services.
SMART_WINDOWS = {"restaurant": ("14:00", "16:00"), "bar": ("14:00", "17:00"),
                 "default": ("14:00", "17:00")}


def smart_window(business_type=""):
    bt = (business_type or "").lower()
    if "restaurant" in bt or "cafe" in bt or "diner" in bt:
        return SMART_WINDOWS["restaurant"]
    if "bar" in bt or "pub" in bt or "tavern" in bt or "brew" in bt:
        return SMART_WINDOWS["bar"]
    return SMART_WINDOWS["default"]
