#!/usr/bin/env python3
import os
import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from unittest.mock import MagicMock

class MockWebElement:
    """A mock implementation of Selenium's WebElement."""
    
    def __init__(self, element_id, tag_name, attributes=None, text=None):
        self.id = element_id
        self.tag_name = tag_name
        self.attributes = attributes or {}
        self._text = text
        self._is_displayed = True
        self._is_enabled = True
        self._children = []
        self._parent = None
        self._mock_clicks = 0
        
    def get_attribute(self, name):
        """Get an attribute value."""
        return self.attributes.get(name)
    
    def click(self):
        """Simulate clicking on the element."""
        if not self._is_displayed:
            raise ElementNotVisibleException(f"Element {self.id} is not visible")
        if not self._is_enabled:
            raise ElementNotInteractableException(f"Element {self.id} is not interactable")
        self._mock_clicks += 1
        
        # If this is a dropdown toggle, simulate showing the dropdown
        if 'dropdown-toggle' in self.get_attribute('class', ''):
            # Find dropdown menu
            for child in self._children:
                if child.tag_name == 'ul' and 'dropdown-menu' in child.get_attribute('class', ''):
                    child._is_displayed = True
                    # Also add 'open' to parent's class
                    if self._parent:
                        classes = self._parent.get_attribute('class', '').split()
                        if 'open' not in classes:
                            classes.append('open')
                            self._parent.attributes['class'] = ' '.join(classes)
        
    def send_keys(self, *value):
        """Simulate typing into the element."""
        if not self._is_displayed:
            raise ElementNotVisibleException(f"Element {self.id} is not visible")
        if not self._is_enabled:
            raise ElementNotInteractableException(f"Element {self.id} is not interactable")
        
        # Combine all values
        input_text = ''.join(str(v) for v in value)
        
        # Update the element's value attribute
        self.attributes['value'] = input_text
        
    @property
    def text(self):
        """Get the element's text."""
        return self._text
    
    def is_displayed(self):
        """Check if element is visible."""
        return self._is_displayed
    
    def is_enabled(self):
        """Check if element is enabled."""
        return self._is_enabled
    
    def find_element(self, by, value):
        """Find an element among children."""
        for child in self._children:
            if self._matches_selector(child, by, value):
                return child
        raise NoSuchElementException(f"Cannot find element with {by}={value}")
    
    def find_elements(self, by, value):
        """Find all matching elements among children."""
        return [child for child in self._children if self._matches_selector(child, by, value)]
    
    def _matches_selector(self, element, by, value):
        """Check if element matches the selector."""
        if by == By.ID:
            return element.get_attribute('id') == value
        elif by == By.TAG_NAME:
            return element.tag_name == value
        elif by == By.CLASS_NAME:
            classes = element.get_attribute('class', '').split()
            return value in classes
        elif by == By.NAME:
            return element.get_attribute('name') == value
        elif by == By.XPATH:
            # Very basic XPath handling - just for the elements we know about
            if value == "//button[contains(@class, 'btn-outline-primary') and contains(@class, 'm-l-xs')]":
                return (element.tag_name == 'button' and 
                       'btn-outline-primary' in element.get_attribute('class', '') and
                       'm-l-xs' in element.get_attribute('class', ''))
            elif '[@id=' in value:
                # Extract ID from XPath
                import re
                id_match = re.search(r'\[@id=[\'"]([^\'"]+)[\'"]\]', value)
                if id_match:
                    return element.get_attribute('id') == id_match.group(1)
            # Our specific ePortem XPaths from the real code
            elif '_ststart' in value:
                return element.get_attribute('id') == '_ststart'
            elif '_stpause' in value:
                return element.get_attribute('id') == '_stpause'
            elif '_stini' in value:
                return element.get_attribute('id') == '_stini'
            elif '_ststop' in value:
                return element.get_attribute('id') == '_ststop'
            elif 'btn-primary' in value:
                return (element.tag_name == 'button' and 
                       'btn-primary' in element.get_attribute('class', ''))
            elif 'btn-warning' in value:
                return (element.tag_name == 'button' and 
                       'btn-warning' in element.get_attribute('class', ''))
        return False

class MockWebDriver(WebDriver):
    """A mock implementation of Selenium's WebDriver."""
    
    def __init__(self):
        # We don't call super().__init__() because we're mocking
        self.current_url = 'about:blank'
        self._mock_pages = self._build_mock_pages()
        self._current_page = None
        
    def get(self, url):
        """Navigate to a URL."""
        self.current_url = url
        
        # Determine which mock page to load
        if '/Usuario/Login' in url:
            self._current_page = self._mock_pages['login']
        elif '/aplicaciones' in url:
            self._current_page = self._mock_pages['dashboard']
        else:
            self._current_page = MockWebElement('body', 'body', text='Page not implemented')
    
    def find_element(self, by, value):
        """Find an element in the current page."""
        if self._current_page is None:
            raise Exception("No page loaded. Call get() first.")
        
        if by == By.NAME and value in ['user', 'password']:
            # Special case for login form fields
            for element in self._iterate_elements(self._current_page):
                if element.get_attribute('name') == value:
                    return element
        
        try:
            return self._current_page.find_element(by, value)
        except NoSuchElementException:
            # Try searching deeper in the DOM tree
            for element in self._iterate_elements(self._current_page):
                try:
                    if self._current_page._matches_selector(element, by, value):
                        return element
                except:
                    pass
            raise NoSuchElementException(f"Cannot find element with {by}={value}")
    
    def _iterate_elements(self, element):
        """Recursively iterate through all elements in the DOM tree."""
        yield element
        for child in element._children:
            yield from self._iterate_elements(child)
    
    def find_elements(self, by, value):
        """Find all matching elements in the current page."""
        if self._current_page is None:
            raise Exception("No page loaded. Call get() first.")
        
        results = []
        for element in self._iterate_elements(self._current_page):
            try:
                if element._matches_selector(element, by, value):
                    results.append(element)
            except:
                pass
        return results
    
    def quit(self):
        """Quit the driver."""
        self._current_page = None
    
    def _build_mock_pages(self):
        """Build the mock DOM for our test pages."""
        pages = {}
        
        # Login page
        login_page = MockWebElement('login-page', 'html')
        login_body = MockWebElement('login-body', 'body')
        login_form = MockWebElement('login-form', 'form', {'action': '/Usuario/Login', 'method': 'post'})
        username_input = MockWebElement('username', 'input', {'name': 'user', 'type': 'text'})
        password_input = MockWebElement('password', 'input', {'name': 'password', 'type': 'password'})
        login_button = MockWebElement('login-button', 'button', {'type': 'submit'}, 'Login')
        
        login_form._children = [username_input, password_input, login_button]
        login_body._children = [login_form]
        login_page._children = [login_body]
        pages['login'] = login_page
        
        # Dashboard page
        dashboard = MockWebElement('dashboard', 'html')
        body = MockWebElement('body', 'body', {'class': 'pace-done skin-1 fixed-sidebar'})
        wrapper = MockWebElement('wrapper', 'div', {'id': 'wrapper'})
        page_wrapper = MockWebElement('page-wrapper', 'div', {'id': 'page-wrapper'})
        wrapper_content = MockWebElement('wrapper-content', 'div', {'class': 'wrapper wrapper-content'})
        row = MockWebElement('row', 'div', {'class': 'row'})
        col = MockWebElement('col', 'div', {'class': 'col-lg-6 col-sm-12'})
        ibox = MockWebElement('ibox', 'div', {'class': 'ibox'})
        ibox_content = MockWebElement('ibox-content', 'div', {'class': 'ibox-content'})
        row2 = MockWebElement('row2', 'div', {'class': 'row'})
        buttons_box = MockWebElement('buttons-box', 'div', {'id': 'buttonsRegBox'})
        btn_group1 = MockWebElement('btn-group1', 'div', {'class': 'btn-group'})
        btn_group2 = MockWebElement('btn-group2', 'div', {'class': 'btn-group'})
        
        # Primary dropdown (Start/Stop)
        primary_button = MockWebElement('primary-button', 'button', {
            'class': 'btn btn-outline btn-block btn-primary dropdown-toggle',
            'data-toggle': 'dropdown'
        }, 'Start / Stop')
        primary_menu = MockWebElement('primary-menu', 'ul', {'class': 'dropdown-menu scrollable-menu'})
        primary_menu._is_displayed = False
        li1 = MockWebElement('li1', 'li')
        ul1 = MockWebElement('ul1', 'ul')
        li_start = MockWebElement('li-start', 'li')
        a_start = MockWebElement('a-start', 'a', {'id': '_ststart'}, 'Start Work (Office)')
        li_pause = MockWebElement('li-pause', 'li')
        a_pause = MockWebElement('a-pause', 'a', {'id': '_stpause'}, 'Pause for Lunch')
        li_stop = MockWebElement('li-stop', 'li')
        a_stop = MockWebElement('a-stop', 'a', {'id': '_ststop'}, 'End Workday')
        
        # Home button
        home_button = MockWebElement('home-button', 'button', {'class': 'btn btn-outline-primary m-l-xs'}, 'Home Options')
        
        # Warning dropdown (Resume)
        btn_group3 = MockWebElement('btn-group3', 'div', {'class': 'btn-group'})
        btn_group4 = MockWebElement('btn-group4', 'div', {'class': 'btn-group'})
        warning_button = MockWebElement('warning-button', 'button', {
            'class': 'btn btn-outline btn-block btn-warning dropdown-toggle',
            'data-toggle': 'dropdown'
        }, 'Resume Work')
        warning_menu = MockWebElement('warning-menu', 'ul', {'class': 'dropdown-menu scrollable-menu'})
        warning_menu._is_displayed = False
        li2 = MockWebElement('li2', 'li')
        ul2 = MockWebElement('ul2', 'ul')
        li_resume_office = MockWebElement('li-resume-office', 'li')
        a_resume_office = MockWebElement('a-resume-office', 'a', {'id': '_stini'}, 'Resume (Office)')
        li_resume_home = MockWebElement('li-resume-home', 'li')
        a_resume_home = MockWebElement('a-resume-home', 'a', {'id': '_stini'}, 'Resume (Home)')
        
        # Build DOM structure
        li_start._children = [a_start]
        li_pause._children = [a_pause]
        li_stop._children = [a_stop]
        ul1._children = [li_start, li_pause]
        li1._children = [ul1]
        primary_menu._children = [li1, li_stop]
        btn_group2._children = [primary_button, primary_menu]
        
        li_resume_office._children = [a_resume_office]
        li_resume_home._children = [a_resume_home]
        ul2._children = [li_resume_office, li_resume_home]
        li2._children = [ul2]
        warning_menu._children = [li2]
        btn_group4._children = [warning_button, warning_menu]
        
        # Set parent references
        primary_menu._parent = btn_group2
        warning_menu._parent = btn_group4
        
        btn_group1._children = [btn_group2, home_button]
        btn_group3._children = [btn_group4]
        buttons_box._children = [btn_group1, btn_group3]
        row2._children = [buttons_box]
        ibox_content._children = [row2]
        ibox._children = [ibox_content]
        col._children = [ibox]
        row._children = [col]
        wrapper_content._children = [row]
        page_wrapper._children = [wrapper_content]
        wrapper._children = [page_wrapper]
        body._children = [wrapper]
        dashboard._children = [body]
        pages['dashboard'] = dashboard
        
        return pages

class ElementNotVisibleException(Exception):
    """Exception raised when interacting with an element that isn't visible."""
    pass

class ElementNotInteractableException(Exception):
    """Exception raised when interacting with an element that isn't interactable."""
    pass

def create_mock_driver():
    """Create and return a new MockWebDriver instance."""
    return MockWebDriver()

if __name__ == "__main__":
    # Example usage
    driver = create_mock_driver()
    driver.get("https://eportem.es/Usuario/Login")
    
    # Find and fill username and password
    username = driver.find_element(By.NAME, "user")
    password = driver.find_element(By.NAME, "password")
    
    username.send_keys("test_user")
    password.send_keys("test_password")
    
    # Submit the form
    password.submit()
    
    # Navigate to dashboard
    driver.get("https://eportem.es/aplicaciones")
    
    # Test finding elements
    try:
        start_button = driver.find_element(By.XPATH, "//button[contains(@class, 'btn-primary')]")
        print(f"Found start button: {start_button.text}")
        start_button.click()
        
        start_action = driver.find_element(By.ID, "_ststart")
        print(f"Found start action: {start_action.text}")
        start_action.click()
        
        print("Test successful!")
    except Exception as e:
        print(f"Test failed: {e}")
    
    driver.quit()