import requests
import os
from tqdm import tqdm
import math
import subprocess
from subprocess import CalledProcessError
from csv import DictWriter
import json
import mimetypes


class AvalonBase:
    def __init__(self, prod_or_pre="pre"):
        self.key = self.__get_key(prod_or_pre)
        self.headers = {
            "Avalon-Api-Key": self.key
        }
        self.base = self.__set_prod_or_pre(prod_or_pre)

    @staticmethod
    def __get_key(prod_or_pre):
        if prod_or_pre == "prod":
            return os.getenv("AVALON_PROD")
        else:
            return os.getenv("AVALON_PRE")
        
    @staticmethod
    def __set_prod_or_pre(environment):
        if environment == "prod":
            return "https://avalon.library.tamu.edu"
        else:
            return "https://avalon-pre.library.tamu.edu"
        
    def get(self, url):
        response = requests.get(
            url, headers=self.headers
        )
        return response.json()
    
    def add_supplemental_file(self, url, file_path, filename=None):
        """
        Upload a supplemental file using multipart form data
        """
        if filename is None:
            filename = os.path.basename(file_path)
        
        # Detect MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type is None:
            mime_type = 'application/octet-stream'  # Default fallback
        
        try:
            with open(file_path, 'rb') as file:
                # Use files parameter for multipart form data
                files = {
                    'file': (filename, file, mime_type)
                }
                
                response = requests.post(
                    url,
                    files=files,
                    headers=self.headers  # Don't add Content-Type - requests handles it
                )
            return response
            
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            return None
        except Exception as e:
            print(f"Error uploading file: {str(e)}")
            return None


class AvalonCollection(AvalonBase):
    def __init__(self, identifier, prod_or_pre="pre"):
        super().__init__(prod_or_pre)
        self.identifier = identifier

    def get_collection(self):
        url = f"{self.base}/admin/collections/{self.identifier}.json"
        return self.get(url)
    
    def get_all_collections(self):
        url = url = f"{self.base}/admin/collections.json"
        return self.get(url)
    
    def get_items(self, verbose=True, page=None, per_page=5):
        if not page:
            url = f"{self.base}/admin/collections/{self.identifier}/items.json"
        else:
            url = f"{self.base}/admin/collections/{self.identifier}/items.json?per_page={per_page}&page={page}"
        if verbose:
            return self.get(url)
        else:
            return list(self.get(url).keys())
        
    def page_items(self, verbose=True, items_per_page=10):
        """ pages through all titles until it has all members
        """ 
        all_items = {}
        number_of_items = self.get_collection().get("object_count", {}).get("total", 0)
        total_pages = math.ceil(number_of_items / items_per_page)
        iterator = tqdm(range(1, total_pages + 1), desc="Fetching items", disable=not verbose)
        for page in iterator:
            new_items = self.get_items(page=page, per_page=items_per_page)
            for k, v in new_items.items():
                all_items[k]=v
        return all_items
    
    def write_csv(self, data):
        all_data = []
        for item, value in data.items():
            work_id = value.get('id')
            for file in value['files']:
                for filename in file['files']:
                    if 'low' in filename['label'] or 'medium' in filename['label']:
                        current = {
                            "Parent work": work_id,
                            "File id": file['id'],
                            "HLS Path": filename['hls_url'],
                            "File duration": filename['duration'],
                            "Original file": filename['derivativeFile'].split('/')[-1],
                            "File quality": filename['label']
                        }
                        break
                all_data.append(current)
        with open("corina.csv", "w") as my_csv:
            writer = DictWriter(my_csv, fieldnames=all_data[0].keys())
            writer.writeheader()
            for row in all_data:
                writer.writerow(row)
    
    def download_best_files(self, output):
        all_items = self.page_items()
        for item, value in all_items.items():
            work_id = value["id"]
            for file in value['files']:
                found = False
                path = ""
                for filename in file['files']:
                    if 'low' in filename['label'] or 'medium' in filename['label']:
                        path = filename['hls_url']
                        found = True
                        break
                current = {
                    "work_id": work_id,
                    "file_id": file['id'],
                    "found": found,
                    "path": path
                }
                command = [
                    "ffmpeg",
                    "-i", current.get('path'),
                    "-vn",
                    "-af", "highpass=f=100, lowpass=f=8000, afftdn, loudnorm",
                    "-acodec", "libmp3lame",
                    "-q:a", "2",
                    f"{output}/{current.get('work_id')}_{current.get("file_id")}.mp3"
                ]
                os.makedirs(output, exist_ok=True)
                if os.path.exists(f"{output}/{current.get('work_id')}_{current.get("file_id")}.mp3"):
                    pass
                else:
                    try:
                        subprocess.run(command, check=True)
                    except CalledProcessError:
                        # Todo: This needs to be investigated Better Handled
                        print(f"Failed to download {current.get("file_id")} from {current.get('work_id')}")

    def get_json(self, json_file):
        response = self.page_items()
        with open(json_file, "w") as my_file:
            json.dump(response, my_file, indent=4)


class AvalonMediaObject(AvalonBase):
    # TODO: Rename as AvalonTitle
    def __init__(self, identifier, prod_or_pre="pre"):
        super().__init__(prod_or_pre)
        self.identifier = identifier

    def get_object(self):
        # Todo: Rename to get
        url = f"{self.base}/media_objects/{self.identifier}.json"
        return self.get(url)
    
    def get_metadata_elements(self):
        response = self.get_object()
        metadata = {
            "Title": response['title'],
            'Collection': response['collection'],
            "Contributors": " | ".join(response['main_contributors']),
            "Link to resource": f"{self.base}/media_objects/{self.identifier}",
            "Publisher": " | ".join(response['fields']['publisher']),
            "Subjects": " | ".join(response['fields']['subject']),
            "Rights information": response['fields']["terms_of_use"]
        }
        return metadata

    def get_json(self):
        response = self.get_object()
        with open("example.json", "w") as my_file:
            json.dump(response, my_file, indent=4)

    def update_offsets(self, offset):
        #@TODO: This needs implementation.  Offset needs to live on a master file which has no direct API.
        #@TODO: This throws a 500 -- investigate
        url = f"{self.base}/media_objects/{self.identifier}.json"
        
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            url,
            json={
                "thumbnail_offset": offset,
                "poster_offset": offset
            },  
            headers=headers
        )
        print(response.status_code)
        return response.content


class AvalonSupplementalFile(AvalonBase):
    def __init__(self, fedora_id, prod_or_pre="pre"):
        super().__init__(prod_or_pre)
        self.fedora_id = fedora_id

    def get_file(self, identifier):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files/{identifier}.json"
        return self.get(url)
    
    def get_files(self):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files.json"
        return self.get(url)
    
    def get_json(self, identifier):
        response = self.get_file(identifier)
        with open("example_file.json", "w") as my_file:
            json.dump(response, my_file, indent=4)

    def add_suppl_filename(self, identifier, filename, metadata=None):
        if metadata is None:
            json={"label": filename}
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files/{identifier}.json"
        
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            url,
            json=metadata,  # Use json parameter instead of data
            headers=headers
        )
        return response.content
    
    def treat_as_transcript(self, identifier):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files/{identifier}.json"
        
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            url,
            json={"treat_as_transcript": True},  # Use json parameter instead of data
            headers=headers
        )
        print(response.status_code)
        return response.content

    def add_pdf(self, file_path, filename=None, mime_type=None):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files.json"
        if filename is None:
            filename = os.path.basename(file_path)
        if mime_type:
            try:
                with open(file_path, 'rb') as file:
                    files = {
                        'file': (filename, file, mime_type)
                    }
                    data = {}
                    metadata = {
                        "label": filename
                    }
                    data['metadata'] = json.dumps(metadata)
                    
                    response = requests.post(
                        url,
                        files=files,
                        data=data,
                        headers=self.headers
                    )
                new_identifer = response.json()['id']
                new_response = self.add_suppl_filename(new_identifer, filename)

                return new_response
                
            except FileNotFoundError:
                print(f"Error: File not found at {file_path}")
                return None
            except Exception as e:
                print(f"Error uploading file: {str(e)}")
                return None
        else:
            return self.add_supplemental_file(url, file_path, filename=filename)
        
    def add_caption_or_transcript(self, file_path, type="caption"):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files.json"
        try:
            if 'vtt' in file_path:
                mimetype = "text/vtt"
            elif 'srt' in file_path:
                mimetype = "text/srt"
            with open(file_path, 'rb') as file:
                files = {
                    'file': (
                        "Captions", 
                        file, 
                        mimetype
                    )
                }
                data = {}
                metadata = {
                    "type": "caption",
                    "label": "Captions in English",
                    "language": "English",
                    "treat_as_transcript": True,
                    "machine_generated": True,
                }
                data['metadata'] = json.dumps(metadata)
                
                response = requests.post(
                    url,
                    files=files,
                    data=data,
                    headers=self.headers
                )
            new_identifer = response.json()['id']
            new_response = self.add_suppl_filename(new_identifer, "Captions", metadata=metadata)

            return new_response
            
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            return None
        except Exception as e:
            print(f"Error uploading file: {str(e)}")
            return None
    
    def _add_file_with_mime_type(self, url, file_path, mime_type):
        """
        Helper method to upload with a specific MIME type
        """
        filename = os.path.basename(file_path)
        
        headers = self.headers.copy()
        headers['Content-Disposition'] = f'file; filename="{filename}"'
        headers['Content-Type'] = mime_type
        
        try:
            with open(file_path, 'rb') as file:
                response = requests.post(
                    url,
                    data=file,
                    headers=headers
                )
            return response
            
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            return None
        except Exception as e:
            print(f"Error uploading file: {str(e)}")
            return None
        
                
if __name__ == "__main__":
    from pprint import pprint
    # collection = "1c18df80p"
    # json_file = "owens.json"
    # collection = "4b29b610g"
    # example = AvalonCollection(collection, prod_or_pre="prod")
    # print(example.get_all_collections())
    # example.download_best_files(f"/Volumes/digital_project_management/avalon_prod_files/{collection}")
    # example.write_csv(all_data)
    # work = "n583xv11k"
    # example = AvalonMediaObject(work, prod_or_pre="prod")
    # example.get_json()
    # example.get_json(json_file)
    # work = "v118rd76r"
    master_file = "v118rd76r"
    # pdf_file = "/Users/mark.baggett/Downloads/gerald-griffin_003_access.caption.vtt"
    # suppl = "97"
    x = AvalonMediaObject(master_file).get_object()
    pprint(x)
    # x = AvalonSupplementalFile(
    #     master_file, 
    #     prod_or_pre="pre"
    # )


    # x.add_pdf(pdf_file, mime_type="application/pdf", filename="Part 1: PDF Transcript")
    # response = x.treat_as_transcript(94)

    # response = x.add_caption_or_transcript(pdf_file)
    # print(response)
    # print(response)
    # print(response)
    # response = x.add_file(pdf_file, mime_type="application/pdf")
    # pprint(response.content)
    # response = x.add_suppl_filename(123, "PDF Transcript")
    # pprint(response)
