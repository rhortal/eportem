#!/usr/bin/env python3
import time
import argparse
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
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']",
                    "button2": None
                },
                "home": {
                    "button1": "//button[contains(@class, 'btn') and contains(@class, 'btn-outline-primary') and contains(@class, 'm-l-xs')]",
                    "button2": "//li/ul/li[2]/a[@id='_ststart']/h2"
                }
            },
            "lunch_break": {
                "office": {
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']",
                    "button2": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[1]/ul/li[1]/a[@id='_stpause']"
                },
                "home": {
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']",
                    "button2": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[1]/ul/li[1]/a[@id='_stpause']"
                }
            },
            "after_lunch": {
                "office": {
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-warning dropdown-toggle']",
                    "button2": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[1]/ul/li[1]/a[@id='_stini']"
                },
                "home": {
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-warning dropdown-toggle']",
                    "button2": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[1]/ul/li[2]/a[@id='_stini']"
                }
            },
            "stop_day": {
                "office": {
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']",
                    "button2": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[2]/a[@id='_ststop']"
                },
                "home": {
                    "button1": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']",
                    "button2": "//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[2]/a[@id='_ststop']"
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
        # Check if we should run
        check_env_variable()
        
        # Log in to ePortem
        self.driver = login_and_navigate(self.driver)
        
        # Find and click the first button
        button1 = self.driver.find_element(By.XPATH, self.selectors["button1"])
        button1.click()
        
        # Click the second button if needed
        if self.selectors["button2"]:
            time.sleep(1)  # Small delay to ensure dropdown is visible
            button2 = self.driver.find_element(By.XPATH, self.selectors["button2"])
            button2.click()
        
        time.sleep(3)
        
        # Close the browser window
        self.driver.quit()
        
        # Send notification
        send_telegram_message(self._get_message())
        
        return True


def execute_action(action_type, location="office", mock=False):
    """Helper function to execute an action with proper setup"""
    driver = None
    if mock:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)
    
    action = EPortemAction(action_type, location, driver)
    return action.perform()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Execute ePortem actions.")
    parser.add_argument("action", choices=["start_day", "lunch_break", "after_lunch", "stop_day"], 
                      help="The action to perform")
    parser.add_argument("--location", choices=["home", "office"], default="office", 
                      help="Location (home or office)")
    parser.add_argument("--mock", action="store_true", help="Run with a mock driver.")
    args = parser.parse_args()
    
    execute_action(args.action, args.location, args.mock)