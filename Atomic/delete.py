from . import Atomic
from . import util
import sys
from Atomic.backendutils import BackendUtils

ATOMIC_CONFIG = util.get_atomic_config()
storage = ATOMIC_CONFIG.get('default_storage', "docker")

class Delete(Atomic):
    def __init__(self):
        super(Delete, self).__init__()
        self.be = None

    def delete_image(self):
        """
        Mark given image(s) for deletion from registry
        :return: 0 if all images marked for deletion, otherwise 2 on any failure
        """
        if self.args.debug:
            util.write_out(str(self.args))

        if (len(self.args.delete_targets) > 0 and self.args.all) or (len(self.args.delete_targets) < 1 and not self.args.all):
            raise ValueError("You must select --all or provide a list of images to delete.")

        beu = BackendUtils()
        delete_objects = []

        # We need to decide on new returns for dbus because we now check image
        # validity prior to executing the delete.  If there is going to be a
        # failure, it will be here.
        #
        # The failure here is basically that it couldnt verify/find the image.

        if self.args.all:
            if self.args.storage:
                self.be = beu.get_backend_from_string(self.args.storage)
                delete_objects = self.be.get_images(get_all=True)
            else:
                delete_objects = beu.get_images(get_all=True)
        else:
            for image in self.args.delete_targets:
                _, img_obj = beu.get_backend_and_image_obj(image, str_preferred_backend=self.args.storage or storage, required=True if self.args.storage else False)
                delete_objects.append(img_obj)

        if self.args.remote:
            return self._delete_remote(self.args.delete_targets)
        if len(delete_objects) == 0:
            raise ValueError("No images to delete.")
        _image_names = []
        for del_obj in delete_objects:
            if del_obj.repotags:
                _image_names.append(len(del_obj.repotags[0]))
            else:
                _image_names.append(len(del_obj.id))
        max_img_name = max(_image_names) + 2

        # When found used imags, we stop action of trying to delete it
        # we then add it to a new list which will be processed
        used_images = []
        all_containers = [x.image for x in beu.get_containers()]
        for image in delete_objects:
            if image.id in all_containers:
                image.used = True

        if not self.args.assumeyes:
            util.write_out("Do you wish to delete the following images?\n")
        else:
            util.write_out("The following images will be deleted.\n")

        three_col = "   {0:" + str(max_img_name) + "} {1:12}  {2}"
        util.write_out(three_col.format("IMAGE", "STORAGE", "USED"))

        unnamed_not_dangling_imgs = []
        for del_obj in delete_objects:
            image = None if not del_obj.repotags else del_obj.repotags[0]
            image_status  = 'YES' if del_obj.used else 'NO'
            if image is None or "<none>" in image:
                if not del_obj.is_dangling:
                    unnamed_not_dangling_imgs.append(del_obj)
                image = del_obj.id[0:12]

            if del_obj.used and not self.args.force:
                used_images.append(del_obj)
            util.write_out(three_col.format(image, del_obj.backend.backend, image_status))

        # always elminate out the unnamed not dangling layer
        delete_objects = [deletable for deletable in delete_objects if deletable not in unnamed_not_dangling_imgs]

        if not self.args.force:
            # redefine the objects that needed to be deleted
            delete_objects = [del_obj for del_obj in delete_objects if del_obj not in used_images]

        if not self.args.assumeyes:
            confirm = util.input("\nConfirm (y/N) ")
            confirm = confirm.strip().lower()
            if not confirm in ['y', 'yes']:
                util.write_err("User aborted delete operation for {}".format(self.args.delete_targets or "all images"))
                sys.exit(2)

        # Perform the delete
        for del_obj in delete_objects:
            del_obj.backend.delete_image(del_obj.input_name, force=self.args.force)

        if not self.args.force:
            # for the used images, output the error messages
            for used_img in used_images:
                util.write_out("Error: conflict: unable to remove repository reference \"{}\"(must-force) - container(s) {} is using its referenced image {}".format(used_img.input_name,
                                beu.get_container_ids_from_image(used_img.id),used_img.id[0:12]))

        for undangling_layer in unnamed_not_dangling_imgs:
            util.write_out("Image {} is an unnamed layer of an image".format(undangling_layer.id[0:12]))

        # We need to return something here for dbus
        return 0

    def prune_images(self):
        """
        Remove dangling images from registry
        :return: 0 if all images deleted or no dangling images found
        """

        if self.args.debug:
            util.write_out(str(self.args))

        beu = BackendUtils()
        for backend in beu.available_backends:
            be = backend()
            be.prune()

        return 0

    def _delete_remote(self, targets):
        results = 0
        for target in targets:
            # _convert_to_skopeo requires registry v1 support while delete requires v2 support
            # args, img = self.syscontainers._convert_to_skopeo(target)

            args = []
            if "http:" in target:
                args.append("--insecure")

            for i in ["oci:", "http:", "https:"]:
                img = target.replace(i, "docker:")

            if not img.startswith("docker:"):
                img = "docker://" + img

            try:
                util.skopeo_delete(img, args)
                util.write_out("Image {} marked for deletion".format(img))
            except ValueError as e:
                util.write_err("Failed to mark Image {} for deletion: {}".format(img, e))
                results = 2
        return results


