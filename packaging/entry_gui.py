import sys

if __name__ == '__main__':
    if '--update-transaction' in sys.argv:
        from secretary.update_transaction import main
    elif '--capture-worker' in sys.argv:
        from secretary.capture_worker import main
    elif '--model-api-worker' in sys.argv:
        from secretary.model_api import main
    else:
        from secretary.launcher import main
    main()
