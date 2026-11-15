import os

from slotwise.web import make_server


def main():
    port = int(os.environ.get('PORT', '8080'))
    if not os.environ.get('PUBLIC_BASE_URL', '').strip():
        raise SystemExit('PUBLIC_BASE_URL is required when binding the demo to 0.0.0.0')
    make_server('0.0.0.0', port).serve_forever()


if __name__ == '__main__':
    main()
