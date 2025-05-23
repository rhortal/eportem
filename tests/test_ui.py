import os
import time
import unittest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

WEB_UI_URL = os.environ.get("WEB_UI_TEST_URL", "http://localhost:8010")


class TestEportemWebUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Use Chrome (matching eportem-action) for UI tests
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--window-size=1200,800")
        cls.driver = webdriver.Chrome(options=chrome_options)
        cls.driver.implicitly_wait(4)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def setUp(self):
        self.driver.get(WEB_UI_URL)

    def test_nav_header_and_footer_present(self):
        # Check header
        nav = self.driver.find_element(By.TAG_NAME, "nav")
        self.assertTrue("Home" in nav.text)
        # Check footer
        foot = self.driver.find_element(By.TAG_NAME, "footer")
        self.assertIn("Roberto Hortal", foot.text)
        self.assertIn(str(time.gmtime().tm_year), foot.text)

    def test_settings_page_loads_and_groups(self):
        # Click settings via header gear icon
        gear = self.driver.find_element(By.ID, "settings-btn")
        gear.click()
        WebDriverWait(self.driver, 4).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )
        # Group titles
        group_titles = [x.text for x in self.driver.find_elements(By.CLASS_NAME, "group-heading")]
        self.assertIn("ePortem Credentials", group_titles)
        self.assertIn("Telegram Settings", group_titles)
        self.assertIn("Slack Settings", group_titles)
        # The Server Settings group is hidden by default. Expand it first:
        server_toggle = self.driver.find_element(By.ID, "server-toggle-btn")
        self.assertTrue("Show" in server_toggle.text)
        server_toggle.click()
        time.sleep(0.5)
        self.assertTrue("Hide" in server_toggle.text)
        group_titles = [x.text for x in self.driver.find_elements(By.CLASS_NAME, "group-heading")]
        self.assertIn("Server Settings", group_titles)
        srv_group = self.driver.find_element(By.ID, "server-group")
        self.assertTrue(srv_group.is_displayed())

    def test_boolean_toggles_and_eye_icon(self):
        self.driver.get(f"{WEB_UI_URL}/settings")
        # Toggle Telegram Notify by id
        telegram_toggle = self.driver.find_element(By.ID, "env-field-TELEGRAM_NOTIFY")
        old_val = telegram_toggle.is_selected()
        telegram_toggle.click()
        self.assertNotEqual(telegram_toggle.is_selected(), old_val)
        # Password field with eye icon
        pw_wrap = self.driver.find_element(By.CLASS_NAME, "settings-password-wrap")
        pw_input = pw_wrap.find_element(By.TAG_NAME, "input")
        eye_btn = pw_wrap.find_element(By.CLASS_NAME, "settings-eye")
        self.assertEqual(pw_input.get_attribute("type"), "password")
        eye_btn.click()
        self.assertEqual(pw_input.get_attribute("type"), "text")
        eye_btn.click()
        self.assertEqual(pw_input.get_attribute("type"), "password")

    def test_invalid_token_shows_error(self):
        self.driver.get(f"{WEB_UI_URL}/settings")
        # Wait for the Telegram Bot Token field to be present
        tg_token = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.ID, "env-field-TELEGRAM_BOT_TOKEN"))
        )
        tg_token.clear()
        tg_token.send_keys("BADTOKEN")
        save_btn = self.driver.find_element(By.ID, "settings-save-btn")
        save_btn.click()
        error_msg = WebDriverWait(self.driver, 3).until(
            EC.presence_of_element_located((By.ID, "settings-error"))
        )
        self.assertTrue("Format invalid" in error_msg.text or "fix all highlighted" in error_msg.text)

    def test_config_warning_overlay_for_missing_env(self):
        # This simulates the overlay by injecting error into the page JS.
        self.driver.execute_script(
            "showConfigWarning('Configuration file not found (.env missing).');"
        )
        ov = self.driver.find_element(By.ID, "config-warning-overlay")
        self.assertTrue(ov.is_displayed())
        btn = ov.find_element(By.TAG_NAME, "button")
        self.assertIn("Open Settings", btn.text)

    def test_footer_year(self):
        foot = self.driver.find_element(By.TAG_NAME, "footer")
        current_year = str(time.gmtime().tm_year)
        self.assertIn(current_year, foot.text)


if __name__ == "__main__":
    unittest.main()
