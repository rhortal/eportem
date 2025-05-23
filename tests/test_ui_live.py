import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

@pytest.mark.usefixtures("flask_server_with_temp_env")
class TestEportemWebUILive:
    @pytest.fixture(autouse=True)
    def setup_driver(self, flask_server_with_temp_env):
        # Launch Chrome as in production/test UI environment
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1200,800")
        self.base_url = flask_server_with_temp_env
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(4)
        yield
        self.driver.quit()

    def test_nav_and_footer(self):
        self.driver.get(self.base_url)
        nav = self.driver.find_element(By.TAG_NAME, "nav")
        assert "Home" in nav.text
        foot = self.driver.find_element(By.TAG_NAME, "footer")
        assert "Roberto Hortal" in foot.text

    def test_settings_page_and_save(self):
        self.driver.get(f"{self.base_url}/settings")
        # Toggle Telegram Notify
        telegram_toggle = self.driver.find_element(By.ID, "env-field-TELEGRAM_NOTIFY")
        start_val = telegram_toggle.is_selected()
        telegram_toggle.click()
        assert telegram_toggle.is_selected() != start_val
        # Set an invalid Telegram token and check error
        tg_token = self.driver.find_element(By.ID, "env-field-TELEGRAM_BOT_TOKEN")
        tg_token.clear()
        tg_token.send_keys("BADTOKEN")
        save_btn = self.driver.find_element(By.ID, "settings-save-btn")
        save_btn.click()
        error_msg = WebDriverWait(self.driver, 3).until(
            EC.presence_of_element_located((By.ID, "settings-error"))
        )
        assert ("Format invalid" in error_msg.text) or ("fix all highlighted" in error_msg.text)
        # Set a valid token, remove error
        tg_token.clear()
        tg_token.send_keys("1745486736:AAEAPhpBIlK9oVS1QEQkSyD0WSbHLRcu23M")
        save_btn.click()
        WebDriverWait(self.driver, 3).until(
            lambda d: "Saved!" in self.driver.find_element(By.ID, "settings-success").text
        )
        succ = self.driver.find_element(By.ID, "settings-success")
        assert "Saved!" in succ.text

    def test_server_settings_expand(self):
        self.driver.get(f"{self.base_url}/settings")
        server_toggle = self.driver.find_element(By.ID, "server-toggle-btn")
        assert "Show" in server_toggle.text
        server_toggle.click()
        assert "Hide" in server_toggle.text
        srv_group = self.driver.find_element(By.ID, "server-group")
        assert srv_group.is_displayed()
