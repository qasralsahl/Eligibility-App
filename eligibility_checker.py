import time
import base64
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class EligibilityChecker:
    def __init__(self, username, password):
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')  # Run in headless mode
            chrome_options.add_argument('--no-sandbox') # Bypass OS security model
            chrome_options.add_argument('--disable-dev-tools')  # Disable DevTools
            chrome_options.add_argument('--disable-gpu')  # Disable GPU hardware acceleration   
            chrome_options.add_argument('--disable-extensions')  # Disable extensions   
            chrome_options.add_argument('--disable-infobars')  # Disable infobars
            chrome_options.add_argument('--disable-browser-side-navigation')  # Disable browser side navigation
            chrome_options.add_argument('--disable-dev-shm-usage')
            self.driver = webdriver.Chrome(options=chrome_options)
            self.wait = WebDriverWait(self.driver, 20)
            self.driver.maximize_window()
            self.username = username
            self.password = password
            print("✅ Browser initialized.")
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Initialization Error: {e}")

    def ensure_page_loaded(self, timeout=10):
        for _ in range(timeout):
            if self.driver.execute_script("return document.readyState") == "complete":
                print("✅ Page fully loaded.")
                return
            time.sleep(1)

    def login_user(self):
        try:
            self.driver.get("https://jet.nnhs.ae/JET")
            self.ensure_page_loaded()

            username_field = self.wait.until(EC.presence_of_element_located((By.ID, "Username")))
            password_field = self.wait.until(EC.presence_of_element_located((By.ID, "Password")))
            print("Element found, Entering Credentials now.....")

            username_field.send_keys(self.username)
            self.driver.execute_script("arguments[0].scrollIntoView(true);", username_field)
            password_field.send_keys(self.password)
            time.sleep(2)

            login_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']")))
            self.driver.execute_script("arguments[0].scrollIntoView(true);", login_button)
            login_button.click()
            time.sleep(2)
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Login failed: {e}")

    def check_login_status(self):
        try:
            current_url = self.driver.current_url.lower()
            if "login" in current_url:
                print("❌ Wrong Credentials.....\n Please try again!")
            else:
                print(f"✅ Logged in successfully, Title: {self.driver.title}")
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Login Status Check Error: {e}")


    def close_modal_eligibility_check_click(self):
        try:
            def close_announcement_modal():
                try:
                    close_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="UsersModalAnnoucement"]/div/div/div[1]/button')))
                    close_btn.click()
                    return True
                except:
                    return False

            time.sleep(1)
            if close_announcement_modal():
                print('✅ Modal closed.')
                el = self.wait.until(EC.element_to_be_clickable((By.ID, 'EligibilityColumn')))
                el.click()
            print("close_modal_eligibility_check_click Done")
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Modal close error: {e}")

    def select_radio_button(self, option):
        try:
            self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "sellogo")))
            button_id = "RadioNAS" if option.lower() == "nas" else "RadioNeuron"
            radio = self.driver.find_element(By.ID, button_id)
            self.driver.execute_script("arguments[0].scrollIntoView();", radio)
            if not radio.is_selected():
                radio.click()
            print(f"Selected {option.upper()} option.")
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Radio button error: {e}")

    def fill_eligibility_form(self, eid, mobile_num, service_network):
        try:
            print(f"Filling form for {eid} with mobile {mobile_num}")
            self.ensure_page_loaded()
            self.close_modal_eligibility_check_click()
            self.select_radio_button(service_network)

            self.wait.until(EC.element_to_be_clickable((By.ID, "RadioNationalID"))).click()
            eid_field = self.wait.until(EC.visibility_of_element_located((By.ID, "EligbilityAddNationalID")))
            self.driver.execute_script("arguments[0].scrollIntoView();", eid_field)
            eid_field.clear()
            eid_field.send_keys(eid)

            dropdown = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='ddlTreatmentbasis_chosen']/a/div")))
            self.driver.execute_script("arguments[0].scrollIntoView(true);", dropdown)
            dropdown.click()
            time.sleep(0.5)
            self.wait.until(EC.element_to_be_clickable((By.XPATH, "//*[@id='ddlTreatmentbasis_chosen']/div/ul/li[3]"))).click()

            phone_field = self.wait.until(EC.visibility_of_element_located((By.ID, "txtAddBenefPhone")))
            self.driver.execute_script("arguments[0].scrollIntoView();", phone_field)
            phone_field.clear()
            phone_field.send_keys(mobile_num)

            captcha = self.driver.execute_script("return code;")
            print(f"Captcha: {captcha}")
            captcha_field = self.wait.until(EC.visibility_of_element_located((By.ID, "cpatchaTextBox")))
            self.driver.execute_script("arguments[0].scrollIntoView();", captcha_field)
            captcha_field.send_keys(captcha)

            submit_btn = self.wait.until(EC.element_to_be_clickable((By.ID, "btnSubmitNewEligibility")))
            self.driver.execute_script("arguments[0].scrollIntoView();", submit_btn)
            submit_btn.click()
            print("Form submitted successfully!")
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Form fill error: {e}")
    
    def save_screenshot_and_pdf(self, eid):
        try:
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            screenshot_dir = os.path.join(BASE_DIR, "static")
            os.makedirs(screenshot_dir, exist_ok=True)
            print("Saving screenshot and PDF...")
            self.driver.execute_script("window.scrollBy(0, 83);")
            time.sleep(0.5)
            # self.driver.save_screenshot(f"screenshot_dir{eid}.png")
            self.driver.save_screenshot(os.path.join(screenshot_dir, f"{eid}.png"))
            print(f"Screenshot saved for {eid}")

            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.5)

            pdf = self.driver.execute_cdp_cmd("Page.printToPDF", {"landscape": False, "printBackground": True})
            with open(f"{eid}.pdf", "wb") as f:
                f.write(base64.b64decode(pdf['data']))
            print(f"Saved documents for {eid}")
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ PDF save error: {e}")

    
    def extract_client_info(self, ref_no, request_date, from_date, to_date, at_text):
        try:
            ref_no = ref_no.split("Reference No:")[-1].strip()
            request_date = request_date.split("Request Date:")[-1].strip()
            from_date = from_date.split("Effective from :")[-1].strip()
            to_date = to_date.replace("to", "").strip()
            at_parts = at_text.strip().split("at", 1)
            effective_at = at_parts[1].strip() if len(at_parts) > 1 else ""
            return {
                "Reference_No": ref_no,
                "Request_Date": request_date,
                "Effective_From": from_date,
                "Effective_To": to_date,
                "Effective_At": effective_at
            }
        except Exception as e:
            print(f'Title: {self.driver.title}')
            print(f"❌ Info extraction error: {e}")
            return {}
    
    def parse_member_details(self, input_string):
        """Parse the member policy details into a structured dictionary"""
        # print(f"\n\nInside ftn: Parsing member details...{input_string}\n\n")

        # Remove the 'Member_Policy_Details' part if it exists
        if input_string.startswith("'Member_Policy_Details': '"):
            content = input_string.split("'Member_Policy_Details': '")[1].rstrip("'")
        else:
            content = input_string
        
        # Split the string into lines
        lines = content.split('\n')
        
        # Initialize an empty dictionary
        result = {}
        
        # Process each pair of lines (key and value)
        for i in range(0, len(lines), 2):
            if i + 1 >= len(lines):
                break
                
            key = lines[i].strip()
            value = lines[i+1].strip()
            
            # Convert key to the desired format
            formatted_key = key.replace(' ', '_')
            if formatted_key == 'TPA_Member_ID':
                formatted_key = 'TPA_Member_ID'
            
            result[formatted_key] = value
        # print(f"Returing the Parsed Member Details: {result}")
        # Return the structured dictionary
        return result

    def gether_info(self, eid, tries=2):
        for attempt in range(tries):
            try:
                print(f"🔁 Attempt {attempt + 1} for {eid}...")

                # Wait for key elements
                is_eligibile = self.wait.until(EC.presence_of_element_located((By.ID, 'cphBody_rptResponseFile_dvResult_0')))
                current_url = self.driver.current_url
                if 'EligibilityDetails' not in current_url:
                    raise Exception("❌ Wrong page: Not on EligibilityDetails.")
                else:
                    # Screenshot & PDF
                    self.save_screenshot_and_pdf(eid)

                ref_no = self.wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="cphBody_rptResponseFile_dvMemDet_0"]/div[2]/div[4]/div[1]/div[1]/div')))
                request_date = self.wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="cphBody_rptResponseFile_dvMemDet_0"]/div[2]/div[4]/div[1]/div[2]/div')))
                effective_from = self.wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="cphBody_rptResponseFile_dvMemDet_0"]/div[2]/div[2]/div[1]')))
                effective_to = self.wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="cphBody_rptResponseFile_dvMemDet_0"]/div[2]/div[2]/div[2]')))
                effective_at = self.wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="cphBody_rptResponseFile_dvMemDet_0"]/div[2]/div[2]/div[3]')))
                Notes = ''
                coverage_details = ''
                if is_eligibile.text == 'Eligible': 
                    coverage_details_el = self.wait.until(EC.presence_of_element_located((By.ID, 'cphBody_rptResponseFile_dvMessages_0')))
                    coverage_details = coverage_details_el.text

                    Notes = 'Valid memeber for Service Provider'
                if is_eligibile.text == 'Not Eligible': #write condition for notes in case not eleigible
                    coverage_details = ''
                    not_eligible = self.wait.until(EC.presence_of_element_located((By.ID, 'cphBody_rptResponseFile_dvEligibilityMessage_0')))
                    Notes = not_eligible.text
                
                info = self.extract_client_info(
                    ref_no.text,
                    request_date.text,
                    effective_from.text,
                    effective_to.text,
                    effective_at.text
                )
                
                info['Is_Eligible'] = is_eligibile.text
                info['Coverage_Details'] = coverage_details
                info['Notes'] = Notes
                info['Emirates_ID'] = eid
                info['Member_Policy_Details'] = ''
                if is_eligibile.text == 'Eligible': 
                    try:
                        i_button = self.wait.until(EC.element_to_be_clickable((By.ID, 'cphBody_rptResponseFile_aEligibilityMemberDetails_0')))
                        self.driver.execute_script("arguments[0].click();", i_button)
                        member_policy_details = self.wait.until(EC.presence_of_element_located((By.ID, 'cphBody_upMemperDetails')))
                        # close_modal =  wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="mpeEligibilityDetailsModal"]/div/div/div[1]/button')))
                        # close_modal.click()
                        time.sleep(1)
                        parsed_details = self.parse_member_details(member_policy_details.text)
                        # print(f"From function Call: Parsed Member Policy Details: {parsed_details}")
                        info['Member_Policy_Details'] = parsed_details
                    except Exception as e:
                        print(f'Title: {self.driver.title}')
                        print(f"I Button Error: {e}")
                
                
                redirect_to = 'https://jet.nnhs.ae/JET/Landing.aspx'
                self.driver.get(redirect_to)
                # print Json data nicely
                import json
                data = json.dumps(info, indent=4)
                print(f'\n\n Final Response:\n{data}\n')
                return info # Exit function on success

            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                # if attempt < tries - 1:       #We will do this when instead of page loading waiting something unexpected happens
                #     print("Retrying...\n")
                #     driver.refresh()  # Optional: refresh page
                #     time.sleep(2)
                # else:
                #     print(f"All {tries} attempts failed for {eid}.\n")

    def run(self, eid, mobile_num, service_network):
        try:
            if service_network.lower() in ('nas', 'neuron'):
                self.login_user()
                self.ensure_page_loaded()
                self.check_login_status()
                self.fill_eligibility_form(eid, mobile_num, service_network)
                response = self.gether_info(eid)
                return response
            else:
                return {"status": "error", "message": "Service network must be either 'NAS' or 'Neuron'."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            self.driver.close()
