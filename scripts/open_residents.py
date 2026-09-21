"""Open the private Residents page, without the key ever being printed or put on a command line.

The residents key is the one secret demo_capture guards hardest ("never printed, never on a command line"), so the way to the
page should not be a URL anyone has to paste, screenshot or read out. This builds the link from the key already on this
machine and hands it straight to the browser.

  python scripts/open_residents.py            the residents map
  python scripts/open_residents.py --map      the MAP with the residents layer, which is where the tab lives
  python scripts/open_residents.py --print    print it instead of opening (asks first - it puts a secret on the screen)
"""
import sys, os, webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import demo_capture as dc  # noqa: E402


def main():
    rk = dc.rkey()
    if "--map" in sys.argv:
        u = "%s/map?key=%s&rk=%s" % (dc.APP, dc.key(), rk)
    else:
        u = "%s/residents?rk=%s" % (dc.APP, rk)
    if "--print" in sys.argv:
        print("This puts the residents key on the screen. Not for a screen share or a recording.")
        if input("type yes to print it: ").strip().lower() != "yes":
            return 1
        print(u)
        return 0
    webbrowser.open(u)
    print("opened the residents page in your browser (the key is not shown here)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
