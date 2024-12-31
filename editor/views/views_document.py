from django.shortcuts import get_object_or_404, render
import os

from results import models

# Documents to create
def docs_differences():
	docs_to_add = []
	for document_type, doc_field_name in list(models.DOCUMENT_FIELD_NAMES.items()):
		event_ids = set(models.Document.objects.exclude(event=None).filter(
			document_type=document_type).values_list('event__id', flat=True))
		kwargs={doc_field_name: ""}
		events = models.Event.objects.exclude(**kwargs).exclude(id__in=event_ids)
		for event in events:
			doc_path = getattr(event, doc_field_name)
			new_path = ""
			new_url = ""
			if doc_path[0] == "/":
				new_path = doc_path[1:]
			else:
				new_url = doc_path
			docs_to_add.append((event.id, event.name, document_type, models.DOCUMENT_TYPES[document_type][1],
				doc_path, new_path, new_url))
	return docs_to_add

# Documents to create
def add_docs(request):
	context = {}
	docs_to_add = []
	docs_added = 0
	photos_added = 0
	reviews_added = 0

	docs_to_add = docs_differences()
	for event_id, tmp, doc_type, tmp, tmp, new_path, new_url in docs_to_add:
		doc_load_choice = models.LOAD_TYPE_LOADED if new_path!="" else models.LOAD_TYPE_NOT_LOADED
		event = get_object_or_404(models.Event, pk=event_id)
		document = models.Document(event=event, document_type=doc_type, loaded_type=doc_load_choice,
			upload=new_path if new_path else None, url_source=new_url)
		document.save()
		docs_added += 1
	context['docs_added'] = docs_added
	context['docs_to_add'] = docs_to_add

	for model, doc_type, context_field in [
		(models.Photo, models.DOC_TYPE_PHOTOS, "photos_added"),
		(models.Review, models.DOC_TYPE_IMPRESSIONS, "reviews_added"),
	]:
		photos = model.objects.filter(added_to_docs=False)
		context[context_field] = photos.count()
		for photo in photos:
			document = models.Document(event=photo.event, document_type=doc_type, loaded_type=models.LOAD_TYPE_DO_NOT_TRY,
				upload=None, url_source=photo.url, comment=photo.comment, author=photo.author,
				last_update=photo.last_update, date_posted=photo.date_posted)
			document.save()
			photo.added_to_docs = True
			photo.save()
			docs_to_add.append((photo.event.id, photo.event.name, doc_type, models.DOCUMENT_TYPES[doc_type][1],
				"", "", photo.url))
	return render(request, "editor/add_docs.html", context)

# Documents to create
def docs_without_old_fields():
	docs_to_add = []

	for document_type, doc_field_name in list(models.DOCUMENT_FIELD_NAMES.items()):
		kwargs={('event__' + doc_field_name): ""}
		for document in models.Document.objects.filter(document_type=document_type, **kwargs):
			if document.upload:
				new_value = "/" + document.upload.name
			else:
				new_value = document.url_source
			docs_to_add.append((document.event,	models.DOCUMENT_TYPES[document_type][1],
				document.upload.name, document.url_source, new_value))
	return docs_to_add

# Documents to create
def add_docs_to_old_fields(request):
	docs_added = 0
	docs_to_add = []
	context = {}

	for document_type, doc_field_name in list(models.DOCUMENT_FIELD_NAMES.items()):
		kwargs={('event__' + doc_field_name): ""}
		for document in models.Document.objects.filter(document_type=document_type, **kwargs):
			event = document.event
			if document.upload:
				new_value = "/" + document.upload.name
			else:
				new_value = document.url_source
			setattr(event, doc_field_name, new_value)
			event.save()
			docs_to_add.append((event, models.DOCUMENT_TYPES[document_type][1],
				document.upload.name, document.url_source, new_value))
			docs_added += 1
	context['docs_added'] = docs_added
	context['docs_to_add_old_fields'] = docs_to_add
	return render(request, "editor/add_docs_to_old_fields.html", context)

def find_docs_wo_files():
	bad_docs = []
	for doc in models.Document.objects.exclude(upload='').order_by('id'):
		if not os.path.exists(doc.upload.path):
			bad_docs.append(doc)
	print("Number of bad docs:", len(bad_docs))

def fill_document_ids(): # When there are reviews/photos that are not connected to documents
	global_docs = 0
	local_docs = 0
	for doc_type, model in [(models.DOC_TYPE_PHOTOS, models.Photo), (models.DOC_TYPE_IMPRESSIONS, models.Review)]:
		# for review in model.objects.filter(event_id=7173, document=None):
		for review in model.objects.filter(event__isnull=False, document=None):
			event = review.event
			document = event.document_set.filter(document_type=doc_type, url_source=review.url).first()
			if document:
				review.document = document
				review.save()
				global_docs += 1
			elif review.url.startswith(results_util.SITE_URL):
				local_url = review.url[len(results_util.SITE_URL) + 1:]
				document = event.document_set.filter(document_type=doc_type, upload=local_url).first()
				if document:
					review.document = document
					review.save()
					local_docs += 1
	print('Finished! Global_docs: {}, local_docs: {}'.format(global_docs, local_docs))
