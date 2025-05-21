#!/usr/bin/env python3
import time
import argparse
import os
from selenium.webdriver.common.by import By
from utility.login_and_navigate import login_and_navigate
from utility.telegram_send import send_telegram_message
from utility.env_check import check_env_variable

class EPortemAction:
    def __init__(self, action_type, location="office", driver=None):
        """
        Initialize the EPortem action

        Parameters:
        - action_type: start_day, lunch_break, after_lunch, stop_day
        - location: office, home
        - driver: optional selenium webdriver instance
        """
        self.action_type = action_type
        self.location = location
        self.driver = driver
        self.selectors = self._get_selectors()

    def _get_selectors(self):
        """Return appropriate selectors based on action type and location"""
        selectors = {
            "start_day": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button/div/div[2]/h2",
                    "button2": None
                },
                "home": {
                    "button1": "//*[@id=\"_ststart\"]/h2",
                    "button2": None
                }
            },
            "lunch_break": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_stpause\"]"
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_stpause\"]"
                }
            },
            "after_lunch": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button/div/div[2]/h2",
                    "button2": "//a[@id=\"_stini\" and @name=\"1\"]"
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button/div/div[2]/h2",
                    "button2": "//a[@id=\"_stini\" and @name=\"1293\"]"
                }
            },
            "stop_day": {
                "office": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_ststop\"]"
                },
                "home": {
                    "button1": "//*[@id=\"buttonsRegBox\"]/div/div/button",
                    "button2": "//*[@id=\"_ststop\"]"
                }
            }
        }
        return selectors.get(self.action_type, {}).get(self.location, {})

    def _get_message(self):
        """Return the appropriate notification message"""
        messages = {
            "start_day": f"RePortemed at {self.location}",
            "lunch_break": "RePortemed going to lunch break",
            "after_lunch": "RePortemed back from lunch break",
            "stop_day": "RePortemed done for the day"
        }
        return messages.get(self.action_type, "RePortem action completed")

    def perform(self):
        """Perform the action"""
        use_mock = os.getenv('USE_MOCK_SERVER', 'NO') == 'YES'

        # Check if we should run (unless using mock server)
        if not use_mock:
            check_env_variable()

        # Log in to ePortem
        self.driver = login_and_navigate(self.driver)

        try:
            # Find and click the first button
            button1 = self.driver.find_element(By.XPATH, self.selectors["button1"])
            button1.click()

            # Click the second button if needed
            if self.selectors["button2"]:
                time.sleep(1)  # Small delay to ensure dropdown is visible
                try:
                    button2 = self.driver.find_element(By.XPATH, self.selectors["button2"])
                    button2.click()
                except Exception as e:
                    if use_mock:
                        print(f"Mock driver couldn't find second button: {e}")
                        print(f"Attempting alternative approach for mock driver...")
                        try:
                            # Try finding by ID instead of full XPath in mock mode
                            button_id = self.selectors["button2"].split("'")[-2] if "'" in self.selectors["button2"] else None
                            if button_id:
                                button2 = self.driver.find_element(By.ID, button_id)
                                button2.click()
                        except Exception as e2:
                            print(f"Alternative approach also failed: {e2}")
                            if not use_mock:
                                raise
                    else:
                        raise

            time.sleep(3)
        except Exception as e:
            if not use_mock:
                raise
            else:
                print(f"Mock driver encountered an error: {e}")
                print("Continuing with mock test...")
        finally:
            # Close the browser window
            self.driver.quit()

        # Send notification (unless using mock server)
        if not use_mock:
            send_telegram_message(self._get_message())
        else:
            print(f"MOCK NOTIFICATION: {self._get_message()}")

        return True


def execute_action(action_type, location="office", mock=False, use_mock_server=False):
    """Helper function to execute an action with proper setup"""
    driver = None
    use_mock = use_mock_server or os.getenv('USE_MOCK_SERVER', 'NO') == 'YES'

    if mock or use_mock:
        if use_mock:
            # Use our custom MockWebDriver
            try:
                from mock_server.mock_driver import create_mock_driver
                driver = create_mock_driver()
                print(f"Using mock driver for {action_type} action at {location}")
            except ImportError as e:
                print(f"Warning: Could not import mock driver: {e}")
                print("Falling back to real WebDriver in headless mode")
                mock = True
                use_mock = False

        if mock and not use_mock:
            # Use real Chrome in headless mode
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options as ChromeOptions
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--headless")
            driver = webdriver.Chrome(options=chrome_options)

    action = EPortemAction(action_type, location, driver)
    return action.perform()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute ePortem actions.")
    parser.add_argument("action", choices=["start_day", "lunch_break", "after_lunch", "stop_day", "help"],
                      help="The action to perform")
    parser.add_argument("--location", choices=["home", "office"], default="office",
                      help="Location (home or office)")
    parser.add_argument("--mock", action="store_true", help="Run with a mock driver.")
    parser.add_argument("--use-mock-server", action="store_true", help="Use the mock server instead of real ePortem.")
    args = parser.parse_args()

    if args.action == "help":
        print(
            "\nUSAGE EXAMPLES:\n"
            "  python3 eportem_action.py start_day --location office\n"
            "  python3 eportem_action.py start_day --location home\n"
            "  python3 eportem_action.py lunch_break --location office\n"
            "  python3 eportem_action.py lunch_break --location home\n"
            "  python3 eportem_action.py after_lunch --location office\n"
            "  python3 eportem_action.py after_lunch --location home\n"
            "  python3 eportem_action.py stop_day --location office\n"
            "  python3 eportem_action.py stop_day --location home\n"
            "\n"
            "OPTIONS:\n"
            "  --mock             Run with a mock driver\n"
            "  --use-mock-server  Use the mock server instead of real ePortem\n"
            "\n"
            "ACTIONS:\n"
            "  start_day, lunch_break, after_lunch, stop_day\n"
            "  (use --location to specify 'office' or 'home')\n"
        )
    else:
        execute_action(args.action, args.location, args.mock, args.use_mock_server)
