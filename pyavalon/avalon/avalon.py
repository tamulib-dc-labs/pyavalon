import requests
import os
from tqdm import tqdm
import math
import subprocess
from subprocess import CalledProcessError
from csv import DictWriter
import json
import mimetypes
import webvtt
import re
import uuid
from iiif_prezi3 import Collection
from .metadata import (
    PAIRED_FIELDS,
    diff_fields,
    preserve_paired_fields,
    read_replacement_csv,
    write_repeated_column_csv,
)
from .supplementals import (
    describe_overlap,
    is_pdf,
    read_deletion_csv,
    select_files,
)


def safe_json(obj):
    """
    Serialize to JSON without \" sequences that confuse PHP's fgetcsv.
    Uses \\u0022 (Unicode escape for ") instead - json_decode restores it.
    """
    return json.dumps(obj).replace('\\"', '\\u0022')


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
                    headers=self.headers
                )
            return response
            
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            return None


class AvalonCollection(AvalonBase):
    def __init__(self, identifier, prod_or_pre="pre"):
        super().__init__(prod_or_pre)
        self.identifier = identifier

    def get_collection(self):
        url = f"{self.base}/admin/collections/{self.identifier}.json"
        return self.get(url)
    
    def get_all_collections(self):
        url = f"{self.base}/admin/collections.json"
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

    def page_items_in_range(self, start_page, end_page, verbose=True):
        """Pages through all items from start to end with progress bar"""
        all_items = {}
        total_pages = (end_page - start_page) + 1
        page = start_page

        with tqdm(total=total_pages, desc="Fetching pages", disable=not verbose) as pbar:
            while page <= end_page:
                new_items = self.get_items(
                    page=page,
                    per_page=10
                )
                for k, v in new_items.items():
                    if k in {"status", "error", "errors"}:
                        print(f"Page {page} returned {k} | {v} with items per page set to 10")
                    else:
                        all_items[k] = v

                page += 1
                pbar.update(1)

        return all_items

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
                if k == "status":
                    print(f"Page {page} returned {k} | {v} with items per page set to {items_per_page}")
                elif k == "error":
                    print(f"Page {page} returned {k} | {v} with items per page set to {items_per_page}")
                elif k == "errors":
                    print(f"Page {page} returned {k} | {v} with items per page set to {items_per_page}")
                else:
                    all_items[k] = v
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
                    f"{output}/{current.get('work_id')}_{current.get('file_id')}.mp3"
                ]
                os.makedirs(output, exist_ok=True)
                if os.path.exists(f"{output}/{current.get('work_id')}_{current.get('file_id')}.mp3"):
                    pass
                else:
                    try:
                        subprocess.run(command, check=True)
                    except CalledProcessError:
                        # Todo: This needs to be investigated Better Handled
                        print(f"Failed to download {current.get('file_id')} from {current.get('work_id')}")

    def get_json(self, json_file):
        response = self.page_items()
        with open(json_file, "w") as my_file:
            json.dump(response, my_file, indent=4)

    def make_iiif_collection(self, json_file="collection.json", collection_id="https://tamulib-dc-labs.github.io/iiif/iiif_collection.json"):
        collection_details = self.get_collection()
        response = self.page_items()
        collection = Collection(
            id=collection_id,
            label=collection_details.get("name", ''),
            summary=collection_details.get("description", ''),
            thumbnail={
                "id": f"https://avalon.library.tamu.edu/collections/{self.identifier}/poster",
                "type": "Image"
            }
        )
        for k, v in response.items():
            if v.get('published') and v.get('visibility') == 'public':
                thumbnail = v.get('files')[0].get('id')
                collection.make_manifest(
                    id=f"https://avalon.library.tamu.edu/media_objects/{k}/manifest.json",
                    label=v.get("title"),
                    summary=v.get("summary"),
                    thumbnail={
                        "id": f"https://avalon.library.tamu.edu/master_files/{thumbnail}/thumbnail",
                        "type": "Image"
                    }
                )
        collection_json = collection.json(indent=2)
        with open(json_file, "w") as my_file:
            my_file.write(collection_json)

    AMI_SET_COLUMNS = [
        "node_uuid", "label", "ismemberof", "type", "abstract", "creator", "contributor",
        "date_issued", "language", "subject", "geographic_subject",
        "temporal_subject", "genre_form", "note", "table_of_contents",
        "identifier", "extent", "rights", "digital_publisher", "ismemberof",
        "related_url", "Image", "Document", "iiifmanifest",
    ]

    def _get_vtt_documents(self, work_id):
        """
        Pull every text/vtt "supplementing" annotation out of the work's public
        IIIF manifest and return one URL per underlying supplemental file,
        preferring the /transcripts rendering over /captions.
        """
        manifest = self.get(f"{self.base}/media_objects/{work_id}/manifest.json")
        found = {}
        for canvas in manifest.get("items", []):
            for annotation_page in canvas.get("annotations", []):
                for annotation in annotation_page.get("items", []):
                    body = annotation.get("body", {})
                    if body.get("format") != "text/vtt":
                        continue
                    url = body.get("id", "")
                    supplemental_file_key = url.rsplit("/", 1)[0]
                    if url.endswith("/transcripts") or supplemental_file_key not in found:
                        found[supplemental_file_key] = url
        return list(found.values())

    def create_ami_set(self, output_csv="ami_set.csv", ismemberof="", verbose=True):
        """
        Build an Archipelago AMI set CSV for every member of this collection.
        Image is the Avalon poster of the work's first master file, Document
        is any VTT captions/transcripts attached to the work, and iiifmanifest
        is a link to the work's IIIF manifest.
        """
        all_items = self.page_items(verbose=verbose)
        rows = []
        for work_id, item in tqdm(all_items.items(), desc="Building AMI set", disable=not verbose):
            fields = item.get("fields", {})
            master_files = item.get("files") or []
            poster_master_id = master_files[0]["id"] if master_files else ""
            image_url = f"{self.base}/master_files/{poster_master_id}/poster" if poster_master_id else ""
            other_identifier = fields.get("other_identifier")
            if isinstance(other_identifier, str):
                other_identifier = [other_identifier] if other_identifier else []
            rows.append({
                "node_uuid": str(uuid.uuid4()),
                "ismemberof": "",
                "label": item.get("title", ""),
                "type": "StreamingVideo",
                "abstract": fields.get("abstract") or item.get("summary", ""),
                "creator": safe_json(fields.get("creator") or []),
                "contributor": safe_json(fields.get("contributor") or []),
                "date_issued": fields.get("date_issued") or "",
                "language": safe_json(fields.get("language") or []),
                "subject": safe_json(fields.get("subject") or []),
                "geographic_subject": safe_json(fields.get("geographic_subject") or []),
                "temporal_subject": safe_json(fields.get("temporal_subject") or []),
                "genre_form": safe_json(fields.get("genre") or []),
                "note": safe_json(fields.get("note") or []),
                "table_of_contents": "; ".join(fields.get("table_of_contents") or []),
                "identifier": safe_json([
                    {"value": value, "authority": "local"} for value in (other_identifier or [])
                ]),
                "extent": safe_json(fields.get("physical_description") or []),
                "rights": fields.get("terms_of_use") or "",
                "digital_publisher": "; ".join(fields.get("publisher") or []),
                "ismemberof": ismemberof,
                "related_url": f"{self.base}/media_objects/{work_id}",
                "Image": image_url,
                "Document": ";".join(self._get_vtt_documents(work_id)),
                "iiifmanifest": f"{self.base}/media_objects/{work_id}/manifest.json",
            })
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = DictWriter(f, fieldnames=self.AMI_SET_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return rows

class AvalonMediaObject(AvalonBase):
    # TODO: Rename as AvalonTitle
    def __init__(self, identifier, prod_or_pre="pre"):
        super().__init__(prod_or_pre)
        self.identifier = identifier

    def get_object(self, type="media_object"):
        # Todo: Rename to get
        if type == "media_object":
            url = f"{self.base}/media_objects/{self.identifier}.json"
        elif type == "master_file":
            url = f"{self.base}/master_files/{self.identifier}.json"
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

    def current_fields(self):
        """The work's descriptive metadata as Avalon currently holds it."""
        return self.get_object().get("fields", {}) or {}

    def replace_metadata(self, fields):
        """Replace the named fields on this work.

        Fields not named are left alone by Avalon -- except note,
        other_identifier and related_item_url, which it rebuilds on every
        update whether or not they were sent. Callers should run the payload
        through metadata.preserve_paired_fields first; this method sends
        exactly what it is given.
        """
        url = f"{self.base}/media_objects/{self.identifier}.json"
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'
        response = requests.put(url, json={"fields": fields}, headers=headers)
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"{self.identifier}: Avalon returned {response.status_code} -- {response.text[:300]}"
            )
        return response

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
        return response.content


class AvalonMasterFile(AvalonBase):
    def __init__(self, identifier, prod_or_pre="pre"):
        super().__init__(prod_or_pre)
        self.identifier = identifier
    
    def get_supplemental_files(self):
        url = f"{self.base}/master_files/{self.identifier}/supplemental_files.json"
        return self.get(url)

    def fetch_supplemental_file(self, supplemental_id, max_bytes=None):
        """Download a supplemental file's content.

        The JSON representation carries no content type, so the only way to
        tell a PDF from any other 'generic' attachment is to follow the
        ActiveStorage redirect and look at what comes back.

        Returns (content_type, content).
        """
        url = f"{self.base}/master_files/{self.identifier}/supplemental_files/{supplemental_id}"
        response = requests.get(url, headers=self.headers, stream=True)
        if response.status_code != 200:
            raise RuntimeError(
                f"could not fetch supplemental file {supplemental_id} on {self.identifier}: "
                f"{response.status_code}"
            )
        content_type = response.headers.get("Content-Type", "")
        if max_bytes is None:
            content = response.content
        else:
            content = next(response.iter_content(max_bytes), b"")
            response.close()
        return content_type, content

    def delete_supplemental_file(self, supplemental_id):
        """Remove one supplemental file. Avalon answers 204 with no body."""
        url = f"{self.base}/master_files/{self.identifier}/supplemental_files/{supplemental_id}.json"
        response = requests.delete(url, headers=self.headers)
        if response.status_code not in (200, 202, 204):
            raise RuntimeError(
                f"{self.identifier}/{supplemental_id}: Avalon returned "
                f"{response.status_code} -- {response.text[:300]}"
            )
        return response


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
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files/{identifier}.json"
        
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            url,
            json=metadata,
            headers=headers
        )
        return response.content
    
    def treat_as_transcript(self, identifier):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files/{identifier}.json"
        
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/json'
        
        response = requests.put(
            url,
            json={"treat_as_transcript": True},
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
        else:
            return self.add_supplemental_file(url, file_path, filename=filename)
        
    def add_caption_or_transcript(self, file_path, type="caption", label="Captions in English"):
        url = f"{self.base}/master_files/{self.fedora_id}/supplemental_files.json"
        try:
            if 'vtt' in file_path:
                mimetype = "text/vtt"
                valid = self.is_valid_vtt(file_path)
                if valid[0]:
                    with open(file_path, 'rb') as file:
                        files = {
                            'file': (
                                label, 
                                file, 
                                mimetype
                            )
                        }
                        data = {}
                        metadata = {
                            "type": type,
                            "label": label,
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
                else:
                    print(f"Error. {file_path} has these errors: {valid[1]}")    
            else:
                # @TODO: Readd srts
                print("Cannot add non-VTT this way yet")
                return None
            
        except FileNotFoundError:
            print(f"Error: File not found at {file_path}")
            return None

    @staticmethod    
    def is_valid_vtt(file_path: str) -> bool:
        TIMESTAMP_PATTERN = re.compile(
            r"^(\d{2}:)?\d{2}:\d{2}\.\d{3} --> (\d{2}:)?\d{2}:\d{2}\.\d{3}$"
        )
        errors = []
        try:
            cues = list(webvtt.read(file_path))
        except Exception as e:
            errors.append(f"Parsing failed: {e}")
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines or not lines[0].strip().startswith("WEBVTT"):
            errors.append("Missing or invalid WEBVTT header.")
        for i, line in enumerate(lines, start=1):
            stripped_line = line.strip()
            if "-->" in stripped_line:
                if not TIMESTAMP_PATTERN.match(stripped_line):
                    errors.append(f"Invalid cue timing on line {i}: {stripped_line}")
        if len(errors) > 0:
            return False, errors
        else:
            return True, []
    
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
        
                
def replace_metadata_from_csv(
    csv_path,
    prod_or_pre="pre",
    dry_run=False,
    report_csv="metadata_replacement_report.csv",
    backup_csv="metadata_replacement_backup.csv",
    verbose=True,
):
    """Replace metadata on every work named in a replacement CSV.

    A field is replaced only if its column appears in the CSV at all, so an
    absent column leaves that field alone and an all-blank column clears it.

    Two files are always written, dry run or not: a backup holding the old
    values in the same repeated-column format (feed it back in to undo a run)
    and a report of what changed. Every write is read back and verified,
    because Avalon erases fields that fail validation and still answers 200.
    """
    updates = read_replacement_csv(csv_path)
    report_rows = []
    backup_records = []

    iterator = tqdm(updates, desc="Replacing metadata", disable=not verbose)
    for update in iterator:
        work = AvalonMediaObject(update.work_id, prod_or_pre=prod_or_pre)
        try:
            current = work.current_fields()
        except Exception as error:
            report_rows.append({
                "work id": update.work_id, "field": "", "old value": "", "new value": "",
                "changed": "", "status": f"error fetching: {error}",
            })
            continue

        # Back up the fields this run touches, plus the three Avalon rewrites
        # unprompted, so the backup is a complete undo for what we are about to do.
        backup_fields = {name: current.get(name) for name in update.fields}
        for primary, partner in PAIRED_FIELDS.items():
            backup_fields.setdefault(primary, current.get(primary))
            backup_fields.setdefault(partner, current.get(partner))
        backup_records.append((update.work_id, backup_fields))

        payload = preserve_paired_fields(update.fields, current)
        changes = diff_fields(current, update.fields)

        if dry_run:
            status = "dry run"
        else:
            try:
                work.replace_metadata(payload)
            except Exception as error:
                status = f"error writing: {error}"
            else:
                # Avalon nulls any field that fails validation and still
                # returns 200, so a success response is not proof.
                verified = work.current_fields()
                mismatched = [
                    name for name, wanted in payload.items()
                    if diff_fields(verified, {name: wanted})[name][2]
                ]
                status = "ok" if not mismatched else f"NOT APPLIED: {', '.join(mismatched)}"

        for name, (old, new, changed) in sorted(changes.items()):
            report_rows.append({
                "work id": update.work_id,
                "field": name,
                "old value": " | ".join(old),
                "new value": " | ".join(new),
                "changed": "yes" if changed else "no",
                "status": status,
            })

    if backup_records:
        write_repeated_column_csv(backup_csv, backup_records)
    if report_rows:
        with open(report_csv, "w", newline="", encoding="utf-8") as handle:
            writer = DictWriter(handle, fieldnames=list(report_rows[0].keys()))
            writer.writeheader()
            writer.writerows(report_rows)
    return report_rows


def delete_supplemental_files_from_csv(
    csv_path,
    prod_or_pre="pre",
    dry_run=False,
    backup_directory="deleted_supplemental_files",
    skip_backup=False,
    report_csv="supplemental_deletion_report.csv",
    verbose=True,
):
    """Delete every supplemental file of a given type from each master file.

    The CSV needs a file id column and a type column holding transcript,
    captions or pdf.

    Deletion cannot be undone through the API, so each file is downloaded to
    backup_directory before it is removed unless skip_backup is set.

    'pdf' is the awkward one: Avalon stores PDFs as 'generic', which is also
    what every other non-caption, non-transcript attachment looks like. Each
    candidate is fetched and checked before deletion, and any generic file
    that turns out not to be a PDF is left alone and reported.
    """
    deletions = read_deletion_csv(csv_path)
    rows = []

    if not dry_run and not skip_backup:
        os.makedirs(backup_directory, exist_ok=True)

    for deletion in tqdm(deletions, desc="Deleting supplemental files", disable=not verbose):
        master = AvalonMasterFile(deletion.file_id, prod_or_pre=prod_or_pre)
        try:
            listing = master.get_supplemental_files()
        except Exception as error:
            rows.append({
                "file id": deletion.file_id, "type": deletion.requested_type,
                "supplemental id": "", "label": "", "content type": "",
                "action": "error", "detail": f"could not list files: {error}",
            })
            continue
        if not isinstance(listing, list):
            rows.append({
                "file id": deletion.file_id, "type": deletion.requested_type,
                "supplemental id": "", "label": "", "content type": "",
                "action": "error", "detail": f"unexpected response: {str(listing)[:120]}",
            })
            continue

        candidates = select_files(listing, deletion.requested_type)
        if not candidates:
            rows.append({
                "file id": deletion.file_id, "type": deletion.requested_type,
                "supplemental id": "", "label": "", "content type": "",
                "action": "nothing to delete", "detail": "",
            })
            continue

        overlap = describe_overlap(candidates) if deletion.requested_type == "caption" else []

        for entry in candidates:
            supplemental_id = entry.get("id")
            label = entry.get("label") or ""
            content_type, content, detail = "", None, ""

            # A generic file is only a PDF if its content says so.
            if deletion.requested_type == "pdf":
                try:
                    content_type, content = master.fetch_supplemental_file(supplemental_id)
                except Exception as error:
                    rows.append({
                        "file id": deletion.file_id, "type": deletion.requested_type,
                        "supplemental id": supplemental_id, "label": label,
                        "content type": "", "action": "error",
                        "detail": f"could not verify: {error}",
                    })
                    continue
                if not is_pdf(content_type, content[:8]):
                    rows.append({
                        "file id": deletion.file_id, "type": deletion.requested_type,
                        "supplemental id": supplemental_id, "label": label,
                        "content type": content_type, "action": "skipped",
                        "detail": "generic file is not a PDF; left in place",
                    })
                    continue

            if overlap and entry.get("treat_as_transcript"):
                detail = "also tagged transcript"

            if dry_run:
                rows.append({
                    "file id": deletion.file_id, "type": deletion.requested_type,
                    "supplemental id": supplemental_id, "label": label,
                    "content type": content_type, "action": "would delete", "detail": detail,
                })
                continue

            if not skip_backup:
                try:
                    if content is None:
                        content_type, content = master.fetch_supplemental_file(supplemental_id)
                    target = os.path.join(
                        backup_directory, f"{deletion.file_id}_{supplemental_id}"
                    )
                    with open(target, "wb") as handle:
                        handle.write(content)
                except Exception as error:
                    rows.append({
                        "file id": deletion.file_id, "type": deletion.requested_type,
                        "supplemental id": supplemental_id, "label": label,
                        "content type": content_type, "action": "error",
                        "detail": f"backup failed, nothing deleted: {error}",
                    })
                    continue

            try:
                master.delete_supplemental_file(supplemental_id)
            except Exception as error:
                action, detail = "error", str(error)
            else:
                action = "deleted"
            rows.append({
                "file id": deletion.file_id, "type": deletion.requested_type,
                "supplemental id": supplemental_id, "label": label,
                "content type": content_type, "action": action, "detail": detail,
            })

    if rows:
        with open(report_csv, "w", newline="", encoding="utf-8") as handle:
            writer = DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return rows


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
    # master_file = "v118rd76r"
    # pdf_file = "/Users/mark.baggett/Downloads/gerald-griffin_003_access.caption.vtt"
    # suppl = "97"
    # x = AvalonMediaObject(master_file).get_object()
    # pprint(x)
    # x = AvalonSupplementalFile(
    #     master_file, 
    #     prod_or_pre="pre"
    # )
    # pprint(x.get_files())
    # pprint(x.get_files())


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

    # master_file = "8910jt826"
    # x = AvalonMediaObject(master_file, prod_or_pre="pre")
    # pprint(x.get_object())

    # collection_id = "xd07gs82c"
    # x = AvalonCollection(collection_id, prod_or_pre="pre")
    # results = x.page_items_in_range(3,6)
    # print(results)
    # # results = x.page_items()
    # with open('corinna_error5.json', 'w') as f:
    #     json.dump(results, f, indent=4)

    collection_id = "vd66w0068"
    x = AvalonCollection(collection_id, prod_or_pre="prod")
    x.make_iiif_collection(
         json_file="sci-fi-radio.json"
    )
